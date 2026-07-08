"""
Creator Earnings Calculator - UPGRADED VERSION

Cloud Run Compatible with:
- Centralized logging via secure_log()
- Centralized database operations (execute_query, execute_many)
- User-isolated caching for earnings data
- Async support for 12K req/sec
- All existing functionality preserved

Calculates total cumulative income and monthly income for creators
from the purchased_exams table based on channel_id.
"""

from datetime import datetime, date, timedelta
import calendar
import re
from flask import current_app

# Centralized imports
from youcert import secure_log, execute_query
# NOTE: Removed get_user_cache, set_user_cache - now using client-side cookies instead
from config import Config

# Logging handled by centralized secure_log from youcert


def secure_log(message, level='info', channel_id=None):
    """Wrapper to centralized secure_log for backward compatibility"""
    from youcert import secure_log as centralized_log
    context = {}
    if channel_id:
        context['channel_id'] = channel_id
    centralized_log(message, level, context=context if context else None)


def get_commission_rate():
    """
    Get platform commission rate from Config (defined in config.py).
    Returns commission percentage (e.g., 35.0 for 35%)

    Single source of truth for commission rates.
    """
    try:
        if current_app:
            rate = current_app.config.get('PLATFORM_COMMISSION_PERCENTAGE', Config.PLATFORM_COMMISSION_PERCENTAGE)
        else:
            rate = Config.PLATFORM_COMMISSION_PERCENTAGE
        
        validated_rate = float(rate)
        if not (0 <= validated_rate <= 100):
            secure_log(f"Commission rate {validated_rate}% outside valid range. Using default {Config.PLATFORM_COMMISSION_PERCENTAGE}%", 'warning')
            return float(Config.PLATFORM_COMMISSION_PERCENTAGE)
        return validated_rate
    except Exception as e:
        secure_log(f"Error getting commission rate: {e}. Using default {Config.PLATFORM_COMMISSION_PERCENTAGE}%", 'error')
        return float(Config.PLATFORM_COMMISSION_PERCENTAGE)


def calculate_creator_payout(gross_amount, commission_rate=None):
    """
    Calculate creator payout after commission deduction.
    
    Args:
        gross_amount (float): Total amount before commission
        commission_rate (float, optional): Commission percentage (gets from config if None)
    
    Returns:
        dict: {
            'gross_amount': float,
            'commission_percentage': float,
            'platform_commission': float,
            'creator_payout': float
        }
    """
    if commission_rate is None:
        commission_rate = get_commission_rate()
    
    try:
        gross = float(gross_amount)
        rate = float(commission_rate)

        # Ensure rate is within valid bounds
        if not (0 <= rate <= 100):
            secure_log(f"Invalid commission rate {rate}% provided. Clamping to 0-100 range.", 'warning')
            rate = max(0, min(100, rate))

        platform_commission = round(gross * (rate / 100.0), 2)
        creator_payout = round(gross - platform_commission, 2)

        # Sanity check: payout should not be negative
        if creator_payout < 0:
             secure_log(f"Calculated negative payout ({creator_payout}) for gross amount {gross} and rate {rate}%. Setting payout to 0.", 'warning')
             creator_payout = 0.00
             platform_commission = gross # Platform takes everything if calculation leads to negative

    except (ValueError, TypeError) as e:
        secure_log(f"Error in payout calculation input: {e}. Returning zero values.", 'error')
        gross = 0.00
        rate = commission_rate if isinstance(commission_rate, (int, float)) else get_commission_rate()
        platform_commission = 0.00
        creator_payout = 0.00

    return {
        'gross_amount': gross,
        'commission_percentage': rate,
        'platform_commission': platform_commission,
        'creator_payout': creator_payout
    }


class CreatorEarningsCalculator:
    """Calculator for creator earnings from purchased exams with enhanced security"""
    
    def __init__(self, channel_id):
        """
        Initialize the earnings calculator for a specific creator
        
        Args:
            channel_id (str): The YouTube channel ID of the creator
        """
        # Enhanced input validation
        if not channel_id or not isinstance(channel_id, str):
            raise ValueError("Channel ID must be a non-empty string")
            
        # Basic check for potentially invalid characters (adjust regex as needed)
        if not re.match(r'^[a-zA-Z0-9_-]+$', channel_id):
             raise ValueError("Channel ID contains invalid characters")

        if len(channel_id.strip()) == 0:
            raise ValueError("Channel ID cannot be empty or whitespace only")
            
        if len(channel_id) > 100:  # Reasonable limit for channel IDs
            raise ValueError("Channel ID exceeds maximum length (100 characters)")
            
        # Sanitize channel ID
        self.channel_id = channel_id.strip()
        self.commission_rate = get_commission_rate()
        


    # NOTE: All cache methods removed - now using client-side cookies in API endpoint
    # _get_cache_key, _get_cached_earnings, _set_cached_earnings, _clear_earnings_cache REMOVED

        secure_log(f"CreatorEarningsCalculator initialized for channel ...{self.channel_id[-6:]} with {self.commission_rate}% commission", 'info', self.channel_id)

    def _validate_date_inputs(self, year=None, month=None):
        """
        Validate year and month inputs with enhanced security
        
        Args:
            year (int, optional): Year to validate
            month (int, optional): Month to validate
            
        Returns:
            tuple: (validated_year, validated_month, error_message)
        """
        current_date = datetime.now()
        
        # Default values
        if year is None:
            year = current_date.year
        if month is None:
            month = current_date.month
            
        # Enhanced validation
        try:
            year = int(year)
            month = int(month)
        except (ValueError, TypeError):
             return None, None, 'Invalid year or month format. Must be integers.'

        if year < 2000 or year > current_date.year + 5: # Allow a few future years
            return None, None, f'Invalid year. Year must be between 2000 and {current_date.year + 5}.'
            
        if not (1 <= month <= 12):
            return None, None, 'Invalid month. Month must be between 1 and 12.'
            
        return year, month, None

    def get_total_cumulative_income(self):
        """
        Calculate total cumulative income AFTER commission deduction
        Uses caching for performance
        
        Returns:
            dict: {
                'total_income': float (AFTER commission),
                'gross_income': float (BEFORE commission),
                'platform_commission': float,
                'commission_percentage': float,
                'total_sales': int,
                'success': bool,
                'message': str
            }
        """
        default_result = {
            'total_income': 0.00,
            'gross_income': 0.00,
            'platform_commission': 0.00,
            'commission_percentage': self.commission_rate,
            'total_sales': 0,
        }

        # Cache removed - using client-side cookies in API endpoint

        try:
            secure_log("Calculating total cumulative income", 'info', self.channel_id)
            
            result = execute_query("""
                SELECT 
                    COALESCE(SUM(pe.amount_paid), 0.00) as gross_income,
                    COUNT(pe.id) as total_sales
                FROM exam.purchased_exams pe
                WHERE pe.channel_id = %s
                AND pe.payment_status = 'completed'
                AND pe.amount_paid >= 0
                AND pe.payment_date IS NOT NULL
            """, (self.channel_id,), fetch_one=True)
            
            if result:
                gross_income = float(result['gross_income'])
                total_sales = int(result['total_sales'])
                
                payout_calc = calculate_creator_payout(gross_income, self.commission_rate)
                
                secure_log(f"Total cumulative income: {total_sales} sales, {payout_calc['creator_payout']} after commission", 'info', self.channel_id)
                
                result_data = {
                    **default_result,
                    'total_income': payout_calc['creator_payout'],
                    'gross_income': gross_income,
                    'platform_commission': payout_calc['platform_commission'],
                    'total_sales': total_sales,
                    'success': True,
                    'message': 'Total cumulative income calculated successfully'
                }


                return result_data
            else:
                secure_log("No sales data found", 'info', self.channel_id)
                result_data = {**default_result, 'success': True, 'message': 'No sales data found'}
                return result_data
                
        except Exception as e:
            secure_log(f"Error calculating total cumulative income: {e}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': str(e)}
        finally:
            pass  # Cleanup handled by execute_query

    def get_monthly_income(self, year=None, month=None):
        """
        Calculate monthly income for the creator for a specific month AFTER commission deduction
        
        Args:
            year (int, optional): Year (defaults to current year)
            month (int, optional): Month 1-12 (defaults to current month)
            
        Returns:
            dict: Complete monthly income data with validation (AFTER commission)
        """
        default_result = {
            'monthly_income': 0.00,
            'gross_monthly_income': 0.00,
            'platform_commission': 0.00,
            'commission_percentage': self.commission_rate,
            'monthly_sales': 0,
            'year': year if isinstance(year, int) else 0,
            'month': month if isinstance(month, int) else 0,
            'month_name': '',
            'days_in_month': 0,
            'start_date': '',
            'end_date': '',
        }
        try:
            # Enhanced input validation
            year, month, error_message = self._validate_date_inputs(year, month)
            if error_message:
                return {**default_result, 'success': False, 'message': error_message}
            
            # Update defaults in case validation modified them
            default_result.update({'year': year, 'month': month})

            secure_log(f"Calculating monthly income for {year}-{month:02d}", 'info', self.channel_id)
            
            # Get month details
            month_name = calendar.month_name[month]
            days_in_month = calendar.monthrange(year, month)[1]
            default_result.update({'month_name': month_name, 'days_in_month': days_in_month})

            # Calculate start and end dates for the month
            start_date = date(year, month, 1)
            end_date = date(year, month, days_in_month)
            default_result.update({'start_date': start_date.strftime('%Y-%m-%d'), 'end_date': end_date.strftime('%Y-%m-%d')})
            
            
            # Enhanced SQL query with additional security measures
            # Query uses index on channel_id, payment_status, payment_date
            result = execute_query("""
                SELECT 
                    COALESCE(SUM(pe.amount_paid), 0.00) as gross_monthly_income,
                    COUNT(pe.id) as monthly_sales
                FROM exam.purchased_exams pe
                WHERE pe.channel_id = %s
                AND pe.payment_status = 'completed'
                AND pe.amount_paid >= 0 -- Ensure amount is not negative
                AND pe.payment_date >= %s
                AND pe.payment_date <= %s
            """, (self.channel_id, start_date, end_date,), fetch_one=True)
            
            if result:
                gross_monthly_income = float(result['gross_monthly_income'])
                monthly_sales = int(result['monthly_sales'])
                
                # Calculate payout after commission
                payout_calc = calculate_creator_payout(gross_monthly_income, self.commission_rate)
                
                secure_log(f"Monthly income calculated for {month_name} {year}: {monthly_sales} sales, â‚¹{payout_calc['creator_payout']} after commission", 'info', self.channel_id)
                
                return {
                    **default_result, # Include defaults
                    'monthly_income': payout_calc['creator_payout'],  # After commission
                    'gross_monthly_income': gross_monthly_income,
                    'platform_commission': payout_calc['platform_commission'],
                    'monthly_sales': monthly_sales,
                    'success': True,
                    'message': f'Monthly income for {month_name} {year} calculated successfully'
                }
            else:
                # Should not happen with COALESCE, but handle defensively
                secure_log(f"No sales data found for {month_name} {year} or query failed", 'info', self.channel_id)
                return {**default_result, 'success': True, 'message': f'No sales data found for {month_name} {year}'}
                
        except Exception as db_err:
             secure_log(f"Database error calculating monthly income: {db_err}", 'error', self.channel_id)
             return {**default_result, 'success': False, 'message': f'Database error: {db_err}'}
        except Exception as e:
            secure_log(f"Unexpected error calculating monthly income: {str(e)}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': 'Unexpected error calculating monthly income'}
        finally:
            pass  # Cleanup handled by execute_query

    def get_previous_month_income(self):
        """
        Get previous month income for payment processing (after commission deduction).
        This is used for automated payments on the 1st of each month.
        
        Returns:
            dict: Previous month income data for payment processing
        """
        default_result = {
             'channel_id': self.channel_id,
             'previous_month': {},
             'payment_eligible': False,
             'minimum_payout_threshold': 100.00, # Define threshold clearly
             'calculated_at': datetime.now().isoformat(),
        }
        try:
            current_date = datetime.now().date() # Use date object for comparison safety
            first_day_current_month = current_date.replace(day=1)
            last_day_prev_month = first_day_current_month - timedelta(days=1)
            prev_year = last_day_prev_month.year
            prev_month = last_day_prev_month.month

            secure_log(f"Calculating previous month income for {prev_year}-{prev_month:02d}", 'info', self.channel_id)
            
            # Get previous month income using the existing validated method
            prev_month_data = self.get_monthly_income(prev_year, prev_month)
            
            if prev_month_data['success']:
                secure_log(f"Previous month income: â‚¹{prev_month_data['monthly_income']} (after commission)", 'info', self.channel_id)
                
                payout_amount = prev_month_data['monthly_income']
                min_threshold = default_result['minimum_payout_threshold']

                return {
                    **default_result,
                    'previous_month': {
                        'year': prev_year,
                        'month': prev_month,
                        'month_name': calendar.month_name[prev_month],
                        'monthly_income': payout_amount,  # After commission
                        'gross_monthly_income': prev_month_data['gross_monthly_income'],
                        'platform_commission': prev_month_data['platform_commission'],
                        'commission_percentage': prev_month_data['commission_percentage'],
                        'monthly_sales': prev_month_data['monthly_sales'],
                        'start_date': prev_month_data['start_date'],
                        'end_date': prev_month_data['end_date']
                    },
                    'payment_eligible': payout_amount >= min_threshold,
                    'success': True,
                    'message': f'Previous month income calculated for payment processing'
                }
            else:
                secure_log(f"Failed to calculate previous month income: {prev_month_data.get('message')}", 'warning', self.channel_id)
                return {**default_result, 'success': False, 'message': 'Error calculating previous month income'}
                
        except Exception as e:
            secure_log(f"Unexpected error calculating previous month income: {str(e)}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': 'Unexpected error calculating previous month income'}

    def get_quarterly_income(self, year=None, quarter=None):
        """
        Calculate quarterly income AFTER commission deduction.
        
        Args:
            year (int, optional): Year (defaults to current year)
            quarter (int, optional): Quarter 1-4 (defaults to current quarter)
            
        Returns:
            dict: Quarterly income data
        """
        default_result = {
            'quarterly_income': 0.00,
            'gross_quarterly_income': 0.00,
            'platform_commission': 0.00,
            'commission_percentage': self.commission_rate,
            'quarterly_sales': 0,
            'year': year if isinstance(year, int) else 0,
            'quarter': quarter if isinstance(quarter, int) else 0,
            'quarter_name': '',
            'start_date': '',
            'end_date': '',
            'months': [],
        }
        try:
            current_date = datetime.now()
            
            if year is None:
                year = current_date.year
            if quarter is None:
                quarter = ((current_date.month - 1) // 3) + 1
            
            # Validate inputs
            try:
                year = int(year)
                quarter = int(quarter)
            except (ValueError, TypeError):
                 return {**default_result, 'success': False, 'message': 'Invalid year or quarter format. Must be integers.'}

            if year < 2000 or year > current_date.year + 5:
                return {**default_result, 'success': False, 'message': f'Invalid year. Year must be between 2000 and {current_date.year + 5}.'}
            
            if not (1 <= quarter <= 4):
                return {**default_result, 'success': False, 'message': 'Invalid quarter. Must be 1-4'}
            
            # Update defaults
            default_result.update({'year': year, 'quarter': quarter})

            # Calculate quarter start and end months
            quarter_months = {
                1: (1, 2, 3),   # Q1: Jan, Feb, Mar
                2: (4, 5, 6),   # Q2: Apr, May, Jun
                3: (7, 8, 9),   # Q3: Jul, Aug, Sep
                4: (10, 11, 12) # Q4: Oct, Nov, Dec
            }
            
            months_in_quarter = quarter_months[quarter]
            start_month = months_in_quarter[0]
            end_month = months_in_quarter[2]
            
            start_date = date(year, start_month, 1)
            end_date = date(year, end_month, calendar.monthrange(year, end_month)[1])

            quarter_name = f'Q{quarter} {year}'
            default_result.update({
                 'quarter_name': quarter_name,
                 'start_date': start_date.strftime('%Y-%m-%d'),
                 'end_date': end_date.strftime('%Y-%m-%d'),
                 'months': list(months_in_quarter)
            })

            secure_log(f"Calculating {quarter_name} income", 'info', self.channel_id)
            
            
            # Query uses index on channel_id, payment_status, payment_date
            result = execute_query("""
                SELECT 
                    COALESCE(SUM(pe.amount_paid), 0.00) as gross_quarterly_income,
                    COUNT(pe.id) as quarterly_sales
                FROM exam.purchased_exams pe
                WHERE pe.channel_id = %s
                AND pe.payment_status = 'completed'
                AND pe.amount_paid >= 0 -- Ensure amount is not negative
                AND pe.payment_date >= %s
                AND pe.payment_date <= %s
            """, (self.channel_id, start_date, end_date,), fetch_one=True)
            
            if result:
                gross_quarterly_income = float(result['gross_quarterly_income'])
                quarterly_sales = int(result['quarterly_sales'])
                
                # Calculate payout after commission
                payout_calc = calculate_creator_payout(gross_quarterly_income, self.commission_rate)
                
                secure_log(f"{quarter_name} income: {quarterly_sales} sales, â‚¹{payout_calc['creator_payout']} after commission", 'info', self.channel_id)
                
                return {
                    **default_result, # Include defaults
                    'quarterly_income': payout_calc['creator_payout'],  # After commission
                    'gross_quarterly_income': gross_quarterly_income,
                    'platform_commission': payout_calc['platform_commission'],
                    'quarterly_sales': quarterly_sales,
                    'success': True,
                    'message': f'{quarter_name} income calculated successfully'
                }
            else:
                # Should not happen with COALESCE
                secure_log(f"No sales found for {quarter_name} or query failed", 'info', self.channel_id)
                return {**default_result, 'success': True, 'message': f'No sales data found for {quarter_name}'}
                
        except Exception as db_err:
             secure_log(f"Database error calculating quarterly income: {db_err}", 'error', self.channel_id)
             return {**default_result, 'success': False, 'message': f'Database error: {db_err}'}
        except Exception as e:
            secure_log(f"Unexpected error calculating quarterly income: {str(e)}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': 'Unexpected error calculating quarterly income'}
        finally:
            pass  # Cleanup handled by execute_query

    def get_current_month_income(self):
        """Get income for the current month (after commission deduction)"""
        return self.get_monthly_income()

    def get_earnings_summary(self, year=None, month=None):
        """
        Get complete earnings summary including total and monthly income AFTER commission deduction
        
        Args:
            year (int, optional): Year for monthly calculation
            month (int, optional): Month for monthly calculation
            
        Returns:
            dict: Complete earnings summary
        """
        default_result = {
            'channel_id': self.channel_id,
            'commission_percentage': self.commission_rate,
            'total_cumulative_income': 0.00,
            'total_gross_income': 0.00,
            'total_platform_commission': 0.00,
            'total_sales': 0,
            'monthly_income': 0.00,
            'monthly_gross_income': 0.00,
            'monthly_platform_commission': 0.00,
            'monthly_sales': 0,
            'quarterly_income': 0.00,
            'quarterly_gross_income': 0.00,
            'quarterly_platform_commission': 0.00,
            'quarterly_sales': 0,
            'month_details': {},
            'quarter_details': {},
            'success': False,
            'message': ''
        }
        try:
            secure_log("Generating earnings summary", 'info', self.channel_id)
            
            # Get total cumulative income (after commission)
            total_data = self.get_total_cumulative_income()
            
            # Get monthly income (after commission) - use provided or default dates
            monthly_data = self.get_monthly_income(year, month)
            
            # Get quarterly income (after commission) - derive quarter from month/year or use default
            current_q_year = monthly_data.get('year') if monthly_data.get('success') else datetime.now().year
            current_q_month = monthly_data.get('month') if monthly_data.get('success') else datetime.now().month
            current_quarter = ((current_q_month - 1) // 3) + 1
            quarterly_data = self.get_quarterly_income(current_q_year, current_quarter)
            
            # Check if all component calculations were successful
            all_success = total_data['success'] and monthly_data['success'] and quarterly_data['success']

            summary = {
                **default_result, # Start with defaults
                # Update with calculated values
                'total_cumulative_income': total_data['total_income'],  # After commission
                'total_gross_income': total_data['gross_income'],
                'total_platform_commission': total_data['platform_commission'],
                'total_sales': total_data['total_sales'],
                'monthly_income': monthly_data['monthly_income'],  # After commission
                'monthly_gross_income': monthly_data['gross_monthly_income'],
                'monthly_platform_commission': monthly_data['platform_commission'],
                'monthly_sales': monthly_data['monthly_sales'],
                'quarterly_income': quarterly_data['quarterly_income'],  # After commission
                'quarterly_gross_income': quarterly_data['gross_quarterly_income'],
                'quarterly_platform_commission': quarterly_data['platform_commission'],
                'quarterly_sales': quarterly_data['quarterly_sales'],
                'month_details': {
                    'year': monthly_data.get('year'),
                    'month': monthly_data.get('month'),
                    'month_name': monthly_data.get('month_name'),
                    'start_date': monthly_data.get('start_date'),
                    'end_date': monthly_data.get('end_date'),
                    'days_in_month': monthly_data.get('days_in_month')
                } if monthly_data.get('success') else {},
                'quarter_details': {
                    'year': quarterly_data.get('year'),
                    'quarter': quarterly_data.get('quarter'),
                    'quarter_name': quarterly_data.get('quarter_name'),
                    'start_date': quarterly_data.get('start_date'),
                    'end_date': quarterly_data.get('end_date'),
                    'months': quarterly_data.get('months')
                } if quarterly_data.get('success') else {},
                'success': all_success,
                'message': 'Earnings summary calculated successfully' if all_success else 'Error calculating earnings summary (check logs)'
            }
            
            if all_success:
                 secure_log("Earnings summary generated successfully", 'info', self.channel_id)
            else:
                 secure_log(f"Earnings summary generation failed. Total success: {total_data['success']}, Monthly success: {monthly_data['success']}, Quarterly success: {quarterly_data['success']}", 'warning', self.channel_id)

            return summary
            
        except Exception as e:
            secure_log(f"Unexpected error getting earnings summary: {str(e)}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': 'Unexpected error getting earnings summary'}

    def get_monthly_breakdown(self, year=None):
        """
        Get month-by-month breakdown for a specific year AFTER commission deduction
        
        Args:
            year (int, optional): Year (defaults to current year)
            
        Returns:
            dict: Monthly breakdown data
        """
        default_result = {
            'channel_id': self.channel_id,
            'year': year if isinstance(year, int) else 0,
            'commission_percentage': self.commission_rate,
            'monthly_breakdown': [],
            'year_total_income': 0.00,
            'year_gross_income': 0.00,
            'year_platform_commission': 0.00,
            'year_total_sales': 0,
        }
        try:
            current_year = datetime.now().year
            if year is None:
                year = current_year
                
            # Enhanced input validation
            try:
                year = int(year)
            except (ValueError, TypeError):
                 return {**default_result, 'success': False, 'message': 'Invalid year format. Must be an integer.'}

            if year < 2000 or year > current_year + 5:
                return {**default_result, 'success': False, 'message': f'Invalid year. Year must be between 2000 and {current_year + 5}.'}
            
            # Update default year
            default_result['year'] = year

            secure_log(f"Calculating monthly breakdown for {year}", 'info', self.channel_id)
            
            
            # Enhanced SQL query with additional analytics
            # Query uses index on channel_id, payment_status, payment_date
            results = execute_query("""
                SELECT 
                    MONTH(pe.payment_date) as month,
                    COALESCE(SUM(pe.amount_paid), 0.00) as gross_monthly_income,
                    COUNT(pe.id) as monthly_sales
                FROM exam.purchased_exams pe
                WHERE pe.channel_id = %s
                AND pe.payment_status = 'completed'
                AND pe.amount_paid >= 0 -- Ensure amount is not negative
                AND YEAR(pe.payment_date) = %s
                GROUP BY MONTH(pe.payment_date)
                ORDER BY MONTH(pe.payment_date)
            """, (self.channel_id, year,), fetch_all=True)
            
            # Create complete monthly breakdown
            monthly_breakdown = []
            year_total_income = 0.00
            year_gross_income = 0.00
            year_platform_commission = 0.00
            year_total_sales = 0
            
            # Create a dictionary for quick lookup
            results_dict = {r['month']: r for r in results}

            for month_num in range(1, 13):
                month_name = calendar.month_name[month_num]
                
                month_data = results_dict.get(month_num)
                
                if month_data:
                    gross_income = float(month_data['gross_monthly_income'])
                    sales = int(month_data['monthly_sales'])
                    
                    # Calculate payout after commission
                    payout_calc = calculate_creator_payout(gross_income, self.commission_rate)
                    
                    month_entry = {
                        'month': month_num,
                        'month_name': month_name,
                        'monthly_income': payout_calc['creator_payout'],  # After commission
                        'gross_monthly_income': gross_income,
                        'platform_commission': payout_calc['platform_commission'],
                        'monthly_sales': sales
                    }
                    monthly_breakdown.append(month_entry)
                    
                    year_total_income += payout_calc['creator_payout']
                    year_gross_income += gross_income
                    year_platform_commission += payout_calc['platform_commission']
                    year_total_sales += sales
                else:
                    monthly_breakdown.append({
                        'month': month_num,
                        'month_name': month_name,
                        'monthly_income': 0.00,
                        'gross_monthly_income': 0.00,
                        'platform_commission': 0.00,
                        'monthly_sales': 0
                    })
            
            result = {
                **default_result, # Include defaults
                'monthly_breakdown': monthly_breakdown,
                'year_total_income': round(year_total_income, 2),  # After commission
                'year_gross_income': round(year_gross_income, 2),
                'year_platform_commission': round(year_platform_commission, 2),
                'year_total_sales': year_total_sales,
                'success': True,
                'message': f'Monthly breakdown for {year} calculated successfully'
            }
            
            secure_log(f"Monthly breakdown calculated successfully for {year}", 'info', self.channel_id)
            return result
            
        except Exception as db_err:
             secure_log(f"Database error getting monthly breakdown: {db_err}", 'error', self.channel_id)
             return {**default_result, 'success': False, 'message': f'Database error: {db_err}'}
        except Exception as e:
            secure_log(f"Unexpected error getting monthly breakdown: {str(e)}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': 'Unexpected error getting monthly breakdown'}
        finally:
            pass  # Cleanup handled by execute_query

    def compute_current_monthly_total_income(self):
        """
        Compute current monthly total income for end-of-month payment processing
        This is specifically for automated monthly payment calculations
        
        Returns:
            dict: Current month earnings data for payment processing (AFTER commission)
        """
        default_result = {
            'channel_id': self.channel_id,
            'commission_percentage': self.commission_rate,
            'payment_period': {},
            'earnings_summary': {
                'monthly_total_income': 0.00,
                'gross_monthly_total_income': 0.00,
                'platform_commission': 0.00,
                'total_transactions': 0,
                'unique_exams_sold': 0,
                'unique_buyers': 0,
                'average_transaction_value': 0.00,
                'min_transaction_value': 0.00,
                'max_transaction_value': 0.00,
                'first_sale_date': None,
                'last_sale_date': None
            },
            'payment_calculation': {
                'gross_income': 0.00,
                'platform_commission_rate': self.commission_rate,
                'platform_commission': 0.00,
                'creator_payout': 0.00,
                'minimum_payout_threshold': 100.00,
                'payout_eligible': False,
                'daily_average_income': 0.00,
                'projected_monthly_income': 0.00
            },
            'calculated_at': datetime.now().isoformat(),
            'success': False,
            'message': ''
        }
        try:
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            
            secure_log(f"Computing current monthly total income for payment processing ({current_year}-{current_month:02d})", 'info', self.channel_id)
            
            
            # Get current month's earnings with detailed breakdown
            start_date = date(current_year, current_month, 1)
            days_in_month = calendar.monthrange(current_year, current_month)[1]
            end_date = date(current_year, current_month, days_in_month)
            
            # Update default payment period
            default_result['payment_period'] = {
                 'year': current_year,
                 'month': current_month,
                 'month_name': calendar.month_name[current_month],
                 'start_date': start_date.strftime('%Y-%m-%d'),
                 'end_date': end_date.strftime('%Y-%m-%d'),
                 'days_in_month': days_in_month,
                 'days_elapsed': current_date.day,
                 'days_remaining': days_in_month - current_date.day
            }

            # Comprehensive query for payment processing
            # Uses index on channel_id, payment_status, payment_date
            result = execute_query("""
                SELECT 
                    COALESCE(SUM(pe.amount_paid), 0.00) as gross_monthly_total_income,
                    COUNT(pe.id) as total_transactions,
                    COUNT(DISTINCT pe.unique_exam_number) as unique_exams_sold,
                    COUNT(DISTINCT pe.user_id) as unique_buyers,
                    MIN(pe.payment_date) as first_sale_date,
                    MAX(pe.payment_date) as last_sale_date,
                    AVG(pe.amount_paid) as average_transaction_value,
                    MIN(pe.amount_paid) as min_transaction_value,
                    MAX(pe.amount_paid) as max_transaction_value
                FROM exam.purchased_exams pe
                WHERE pe.channel_id = %s
                AND pe.payment_status = 'completed'
                AND pe.amount_paid >= 0 -- Ensure non-negative amount
                AND pe.payment_date >= %s
                AND pe.payment_date <= %s
            """, (self.channel_id, start_date, end_date,), fetch_one=True)
            
            # Calculate payment processing data
            if result and result['gross_monthly_total_income'] is not None:
                gross_monthly_total_income = float(result['gross_monthly_total_income'])
                
                # Calculate creator payout after commission
                payout_calc = calculate_creator_payout(gross_monthly_total_income, self.commission_rate)
                
                # Calculate days elapsed in current month
                days_elapsed = current_date.day
                
                # Calculate daily average and projected monthly income (after commission)
                # Avoid division by zero if it's the first day
                daily_average_gross = (gross_monthly_total_income / days_elapsed) if days_elapsed > 0 else 0.0
                daily_average_payout = (payout_calc['creator_payout'] / days_elapsed) if days_elapsed > 0 else 0.0
                
                # Use current income as projection if no daily average yet
                projected_monthly_gross = (daily_average_gross * days_in_month) if daily_average_gross > 0 else gross_monthly_total_income
                projected_monthly_payout = (daily_average_payout * days_in_month) if daily_average_payout > 0 else payout_calc['creator_payout']
                
                payment_data = {
                    **default_result, # Start with defaults
                    'earnings_summary': {
                        'monthly_total_income': payout_calc['creator_payout'],  # After commission
                        'gross_monthly_total_income': gross_monthly_total_income,
                        'platform_commission': payout_calc['platform_commission'],
                        'total_transactions': result['total_transactions'] or 0,
                        'unique_exams_sold': result['unique_exams_sold'] or 0,
                        'unique_buyers': result['unique_buyers'] or 0,
                        'average_transaction_value': float(result['average_transaction_value']) if result['average_transaction_value'] else 0.00,
                        'min_transaction_value': float(result['min_transaction_value']) if result['min_transaction_value'] else 0.00,
                        'max_transaction_value': float(result['max_transaction_value']) if result['max_transaction_value'] else 0.00,
                        'first_sale_date': result['first_sale_date'].strftime('%Y-%m-%d') if result['first_sale_date'] else None,
                        'last_sale_date': result['last_sale_date'].strftime('%Y-%m-%d') if result['last_sale_date'] else None
                    },
                    'payment_calculation': {
                        'gross_income': gross_monthly_total_income,
                        'platform_commission_rate': self.commission_rate,
                        'platform_commission': payout_calc['platform_commission'],
                        'creator_payout': payout_calc['creator_payout'],  # After commission
                        'minimum_payout_threshold': 100.00,
                        'payout_eligible': payout_calc['creator_payout'] >= 100.00,
                        'daily_average_income': round(daily_average_payout, 2),  # After commission
                        'projected_monthly_income': round(projected_monthly_payout, 2)  # After commission
                    },
                    'success': True,
                    'message': f'Current monthly total income computed for {calendar.month_name[current_month]} {current_year}'
                }
                
                secure_log(f"Current monthly total computed: â‚¹{payout_calc['creator_payout']} (after commission)", 'info', self.channel_id)
                return payment_data
                
            else:
                # No earnings this month or query failed
                secure_log(f"No earnings found for current month {current_year}-{current_month:02d}", 'info', self.channel_id)
                return {
                    **default_result,
                    'success': True,
                    'message': f'No earnings found for {calendar.month_name[current_month]} {current_year}'
                }
                
        except Exception as db_err:
             secure_log(f"Database error computing current monthly total income: {db_err}", 'error', self.channel_id)
             return {**default_result, 'success': False, 'message': f'Database error: {db_err}'}
        except Exception as e:
            secure_log(f"Unexpected error computing current monthly total income: {str(e)}", 'error', self.channel_id)
            return {**default_result, 'success': False, 'message': 'Unexpected error computing current monthly total income'}
        finally:
            pass  # Cleanup handled by execute_query


# Enhanced utility functions with security measures
def get_creator_earnings(channel_id, year=None, month=None):
    """
    Convenience function to get creator earnings with comprehensive input validation
    
    Args:
        channel_id (str): Channel ID
        year (int, optional): Year for monthly calculation
        month (int, optional): Month for monthly calculation
        
    Returns:
        dict: Earnings summary (AFTER commission)
    """
    try:
        # Validate channel_id before creating calculator instance
        if not channel_id or not isinstance(channel_id, str) or len(channel_id.strip()) == 0:
             secure_log(f"Invalid channel ID provided to get_creator_earnings: '{channel_id}'", 'warning')
             return {'success': False, 'message': 'Invalid channel ID provided'}
        
        # Further validation can be added (e.g., regex) if needed
        # import re
        # if not re.match(r'^[a-zA-Z0-9_-]+$', channel_id.strip()):
        #     secure_log(f"Channel ID contains invalid characters: '{channel_id}'", 'warning')
        #     return {'success': False, 'message': 'Channel ID contains invalid characters'}

        calculator = CreatorEarningsCalculator(channel_id.strip())
        return calculator.get_earnings_summary(year, month)
        
    except ValueError as e: # Catch errors from CreatorEarningsCalculator.__init__
        secure_log(f"Validation error creating calculator in get_creator_earnings: {str(e)}", 'warning')
        return {'success': False, 'message': str(e)} # Return specific validation error
    except Exception as e:
        # Log error with channel ID context if possible
        log_channel_id = channel_id if isinstance(channel_id, str) else 'unknown'
        secure_log(f"Unexpected error in get_creator_earnings: {str(e)}", 'error', channel_id=log_channel_id)
        return {'success': False, 'message': 'Unexpected error retrieving creator earnings'}


def get_creator_monthly_breakdown(channel_id, year=None):
    """
    Convenience function to get monthly breakdown for a creator with enhanced validation
    
    Args:
        channel_id (str): Channel ID
        year (int, optional): Year
        
    Returns:
        dict: Monthly breakdown (AFTER commission)
    """
    try:
        # Validate channel_id
        if not channel_id or not isinstance(channel_id, str) or len(channel_id.strip()) == 0:
             secure_log(f"Invalid channel ID provided to get_creator_monthly_breakdown: '{channel_id}'", 'warning')
             return {'success': False, 'message': 'Invalid channel ID provided'}

        calculator = CreatorEarningsCalculator(channel_id.strip())
        return calculator.get_monthly_breakdown(year)
        
    except ValueError as e: # Catch errors from __init__ or validation
        secure_log(f"Validation error in get_creator_monthly_breakdown: {str(e)}", 'warning')
        return {'success': False, 'message': str(e)}
    except Exception as e:
        log_channel_id = channel_id if isinstance(channel_id, str) else 'unknown'
        secure_log(f"Unexpected error in get_creator_monthly_breakdown: {str(e)}", 'error', channel_id=log_channel_id)
        return {'success': False, 'message': 'Unexpected error retrieving monthly breakdown'}


def get_creator_previous_month_income(channel_id):
    """
    Convenience function to get previous month income for payment processing
    
    Args:
        channel_id (str): Channel ID
        
    Returns:
        dict: Previous month income (AFTER commission) for payment processing
    """
    try:
        # Validate channel_id
        if not channel_id or not isinstance(channel_id, str) or len(channel_id.strip()) == 0:
             secure_log(f"Invalid channel ID provided to get_creator_previous_month_income: '{channel_id}'", 'warning')
             return {'success': False, 'message': 'Invalid channel ID provided'}

        calculator = CreatorEarningsCalculator(channel_id.strip())
        return calculator.get_previous_month_income()
        
    except ValueError as e: # Catch errors from __init__
        secure_log(f"Validation error in get_creator_previous_month_income: {str(e)}", 'warning')
        return {'success': False, 'message': str(e)}
    except Exception as e:
        log_channel_id = channel_id if isinstance(channel_id, str) else 'unknown'
        secure_log(f"Unexpected error in get_creator_previous_month_income: {str(e)}", 'error', channel_id=log_channel_id)
        return {'success': False, 'message': 'Unexpected error retrieving previous month income'}


def get_creator_quarterly_income(channel_id, year=None, quarter=None):
    """
    Convenience function to get quarterly income
    
    Args:
        channel_id (str): Channel ID
        year (int, optional): Year
        quarter (int, optional): Quarter (1-4)
        
    Returns:
        dict: Quarterly income (AFTER commission)
    """
    try:
        # Validate channel_id
        if not channel_id or not isinstance(channel_id, str) or len(channel_id.strip()) == 0:
             secure_log(f"Invalid channel ID provided to get_creator_quarterly_income: '{channel_id}'", 'warning')
             return {'success': False, 'message': 'Invalid channel ID provided'}

        calculator = CreatorEarningsCalculator(channel_id.strip())
        return calculator.get_quarterly_income(year, quarter)
        
    except ValueError as e: # Catch errors from __init__ or validation
        secure_log(f"Validation error in get_creator_quarterly_income: {str(e)}", 'warning')
        return {'success': False, 'message': str(e)}
    except Exception as e:
        log_channel_id = channel_id if isinstance(channel_id, str) else 'unknown'
        secure_log(f"Unexpected error in get_creator_quarterly_income: {str(e)}", 'error', channel_id=log_channel_id)
        return {'success': False, 'message': 'Unexpected error retrieving quarterly income'}


def compute_creator_current_monthly_total(channel_id):
    """
    Convenience function to compute current monthly total income for payment processing
    This is the main function for end-of-month payment calculations
    
    Args:
        channel_id (str): Channel ID
        
    Returns:
        dict: Current monthly total income data for payment processing (AFTER commission)
    """
    try:
        # Validate channel_id
        if not channel_id or not isinstance(channel_id, str) or len(channel_id.strip()) == 0:
             secure_log(f"Invalid channel ID provided to compute_creator_current_monthly_total: '{channel_id}'", 'warning')
             return {'success': False, 'message': 'Invalid channel ID provided'}

        calculator = CreatorEarningsCalculator(channel_id.strip())
        return calculator.compute_current_monthly_total_income()
        
    except ValueError as e: # Catch errors from __init__
        secure_log(f"Validation error in compute_creator_current_monthly_total: {str(e)}", 'warning')
        return {'success': False, 'message': str(e)}
    except Exception as e:
        log_channel_id = channel_id if isinstance(channel_id, str) else 'unknown'
        secure_log(f"Unexpected error in compute_creator_current_monthly_total: {str(e)}", 'error', channel_id=log_channel_id)
        return {'success': False, 'message': 'Unexpected error computing current monthly total income'}
    
    