"""
certificate_generator.py - UPGRADED VERSION

Cloud Run Compatible Certificate Generator with:
- Centralized logging via secure_log()
- Agnostic File Loading via download_file_content() (Supports GCS & Local)
- Cloud Run Font Support (loads fonts from youcert/static/font/)
- No server system font dependencies
- Dynamic URL detection via get_base_url()
- Optimized for 12K req/sec
- All existing functionality preserved
"""

from PIL import Image, ImageDraw, ImageFont
import os
import re
import pyqrcode
from io import BytesIO

# Import centralized logging and storage reader
from youcert import secure_log, download_file_content, get_base_url


# ============================================================================
# FONT HELPER FUNCTIONS
# ============================================================================

def get_font_path(font_filename):
    """
    Get absolute path to font file from multiple possible locations.

    Priority (Cloud Run optimized):
    1. youcert/static/font/ directory (Cloud Run compatible - bundled with app)
    2. Project root directory (backward compatibility for local development)

    Args:
        font_filename (str): Font filename (e.g., 'Poppins-Regular.ttf')

    Returns:
        str: Absolute path to font file or None if not found
    """
    # Get project root directory (2 levels up from this file)
    current_file = os.path.abspath(__file__)
    logic_dir = os.path.dirname(current_file)
    youcert_dir = os.path.dirname(logic_dir)
    project_root = os.path.dirname(youcert_dir)

    # Font search locations (in priority order - Cloud Run optimized)
    font_locations = [
        # 1. youcert/static/font/ directory (Cloud Run compatible - bundled with app)
        os.path.join(youcert_dir, 'static', 'font', font_filename),

        # 2. Project root (backward compatibility for local development)
        os.path.join(project_root, font_filename),
    ]

    # Try each location
    for font_path in font_locations:
        if os.path.exists(font_path):
            secure_log(f"Font found: {font_path}", 'debug')
            return font_path

    # Font not found in any location
    secure_log(f"Font '{font_filename}' not found in any location", 'warning')
    return None


def get_font_at_size(font_filename, initial_size):
    """
    Load font at specified size with fallback.

    Cloud Run Compatible - Uses fonts from project static folder.
    No server system fonts dependency.

    Args:
        font_filename (str): Font filename (e.g., 'Poppins-Regular.ttf')
        initial_size (int): Font size in points

    Returns:
        ImageFont: Font object
    """
    font_path = get_font_path(font_filename)

    if font_path:
        try:
            return ImageFont.truetype(font_path, initial_size)
        except IOError as e:
            secure_log(f"Error loading font '{font_filename}': {e}", 'warning')

    # Fallback to PIL default font
    secure_log(f"Using default font (fallback for '{font_filename}')", 'warning')
    return ImageFont.load_default()


def get_text_bbox(draw, text, font):
    """
    Get text bounding box (handles empty strings).
    
    Args:
        draw (ImageDraw): Draw object
        text (str): Text to measure
        font (ImageFont): Font object
        
    Returns:
        tuple: (left, top, right, bottom) bounding box
    """
    if not text:
        return (0, 0, 0, 0)
    try:
        # Modern PIL
        return draw.textbbox((0, 0), text, font=font)
    except AttributeError:
        # Fallback for older PIL
        width, height = draw.textsize(text, font=font)
        return (0, 0, width, height)


def wrap_text_to_fit(draw, text, font, max_width):
    """
    Wrap text to fit maximum width.
    Fills each line as much as possible before breaking.
    
    Args:
        draw (ImageDraw): Draw object
        text (str): Text to wrap
        font (ImageFont): Font object
        max_width (int): Maximum width in pixels
        
    Returns:
        list: List of wrapped text lines
    """
    lines = []
    words = text.split()
    
    if not words:
        return [""]

    current_line = words[0]
    for word in words[1:]:
        # Check width with new word
        bbox = get_text_bbox(draw, current_line + " " + word, font)
        text_width = bbox[2] - bbox[0]
        
        if text_width <= max_width:
            # Word fits
            current_line += " " + word
        else:
            # Word doesn't fit, new line
            lines.append(current_line)
            current_line = word
    
    # Add last line
    lines.append(current_line)
    return lines


def format_subscriber_count(count):
    """
    Format subscriber count into readable string (e.g., 1.5m subs).
    
    Args:
        count (int): Subscriber count
        
    Returns:
        str: Formatted string like "(1.5m subs)"
    """
    try:
        count = int(count)
    except (ValueError, TypeError):
        return ""

    if count < 1:
        return ""
    
    if count >= 1_000_000:
        val = count / 1_000_000
        num_str = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
        return f"({num_str}m subs)"
    elif count >= 1_000:
        val = count / 1_000
        num_str = f"{int(val)}" if val.is_integer() else f"{val:.1f}"
        return f"({num_str}k subs)"
    else:
        return f"({count} subs)"


# ============================================================================
# CERTIFICATE GENERATION FUNCTION
# ============================================================================

def generate_certificate(
    template_path,
    output_path,
    data,
    verification_base_url=None
):
    """
    Generate certificate with provided data.

    Supports both local development and Cloud Run with GCS/Centralized Storage.

    Args:
        template_path (str): Path to template image
        output_path (str): Output path (PDF will be generated)
        data (dict): Certificate data containing:
            - channel_name: Channel name
            - name: User name
            - youtube_title: Course title
            - course_length: Course duration
            - score: Exam score
            - signature_image_path: Path to signature image (GCS or Local)
            - subscriber_count: Subscriber count
            - qr_code: QR code data
        verification_base_url (str): Base URL for QR code verification (optional)
            If not provided, auto-detects from Flask request (supports custom domains!)
            Auto-detected examples:
                Custom domain: https://www.youcert.com/verify/
                Cloud Run: https://youcert-app-480502.asia-south1.run.app/verify/
                Development: http://127.0.0.1:5000/verify/

    Returns:
        str: Path to generated PDF or False if failed
    """
    try:
        # Open template
        img = Image.open(template_path).convert("RGBA")
        draw = ImageDraw.Draw(img)
        secure_log("Certificate template loaded", 'info')
    except IOError as e:
        secure_log(f"Cannot open template: {template_path} - {e}", 'error')
        return False

    # ========================================================================
    # FIELD 1: CHANNEL NAME (TOP) - LEFT ALIGNED
    # ========================================================================
    # Box: x=1048, y=14, w=874, h=81
    text_channel_name_top = str(data.get('channel_name', '')).upper()
    
    if text_channel_name_top:
        try:
            text_img = Image.new('RGBA', (874, 81), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_img)
            
            font_size = 42
            font_color = "#000080"
            font_path = "Poppins-Regular.ttf"
            font = get_font_at_size(font_path, font_size)
            
            bbox = get_text_bbox(text_draw, text_channel_name_top, font)
            text_width = bbox[2] - bbox[0]
            
            min_font_size = 10
            while text_width > 872 and font_size > min_font_size:
                font_size -= 1
                font = get_font_at_size(font_path, font_size)
                bbox = get_text_bbox(text_draw, text_channel_name_top, font)
                text_width = bbox[2] - bbox[0]
            
            text_height = bbox[3] - bbox[1]
            x_pos_in_box = 0  # Left alignment
            y_pos_in_box = (81 - text_height) // 2 - bbox[1]
            
            text_draw.text(
                (x_pos_in_box, y_pos_in_box), 
                text_channel_name_top, 
                fill=font_color, 
                font=font,
                align="left"
            )
            
            img.paste(text_img, (1048, 14), text_img)
        except Exception as e:
            secure_log(f"Error processing channel name (top): {e}", 'error')

    # ========================================================================
    # FIELD 2: USER NAME - CENTERED
    # ========================================================================
    # Box: x=190, y=467, w=1731, h=160
    text_name = str(data.get('name', ''))
    
    if text_name:
        try:
            text_img = Image.new('RGBA', (1731, 160), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_img)
            
            font_size = 68
            font_path = "Poppins-Regular.ttf"
            font = get_font_at_size(font_path, font_size)
            
            bbox = get_text_bbox(text_draw, text_name, font)
            text_width = bbox[2] - bbox[0]
            
            min_font_size = 10
            while text_width > 1729 and font_size > min_font_size:
                font_size -= 1
                font = get_font_at_size(font_path, font_size)
                bbox = get_text_bbox(text_draw, text_name, font)
                text_width = bbox[2] - bbox[0]
            
            text_height = bbox[3] - bbox[1]
            x_pos_in_box = (1731 - text_width) // 2
            y_pos_in_box = (160 - text_height) // 2 - bbox[1]
            
            text_draw.text(
                (x_pos_in_box, y_pos_in_box), 
                text_name, 
                fill="#1D1D1F", 
                font=font
            )
            
            img.paste(text_img, (175, 467), text_img)
        except Exception as e:
            secure_log(f"Error processing name field: {e}", 'error')
            
    # ========================================================================
    # FIELD 3: YOUTUBE TITLE - SMART WRAP
    # ========================================================================
    # Box: x=176, y=717, w=1764, h=162
    box_width = 1764
    box_height = 162
    box_x = 176
    box_y = 717
    
    text_youtube_title = str(data.get('youtube_title', ''))
    
    if text_youtube_title:
        # Clean hashtags and extra spaces
        text_youtube_title = re.sub(r'#\w+', '', text_youtube_title).strip()
        text_youtube_title = re.sub(r'\s+', ' ', text_youtube_title)

        try:
            text_img = Image.new('RGBA', (box_width, box_height), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_img)
            
            font_size = 58
            font_path = "Poppins-Regular.ttf"
            min_font_size = 10
            
            lines = []
            total_text_height = 0
            line_height = 0

            # Find font size that fits
            while font_size >= min_font_size:
                font = get_font_at_size(font_path, font_size)
                lines = wrap_text_to_fit(text_draw, text_youtube_title, font, box_width - 4)
                
                bbox = get_text_bbox(text_draw, "A", font)
                line_height = bbox[3] - bbox[1] + 5
                total_text_height = len(lines) * line_height
                
                if total_text_height <= box_height:
                    break
                
                font_size -= 2

            # Draw lines
            start_y = (box_height - total_text_height) // 2
            current_y = start_y
            
            for line in lines:
                bbox = get_text_bbox(text_draw, line, font)
                line_width = bbox[2] - bbox[0]
                x_pos = (box_width - line_width) // 2
                
                text_draw.text(
                    (x_pos, current_y), 
                    line, 
                    fill="#1D1D1F", 
                    font=font
                )
                current_y += line_height
            
            img.paste(text_img, (box_x, box_y), text_img)
        except Exception as e:
            secure_log(f"Error processing youtube title: {e}", 'error')

    # ========================================================================
    # FIELD 4: COURSE LENGTH
    # ========================================================================
    # Box: x=1190, y=605, w=260, h=60
    text_course_length = str(data.get('course_length', ''))
    
    if text_course_length:
        try:
            text_img = Image.new('RGBA', (260, 60), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_img)
            
            font_size = 38
            font_path = "Poppins-Regular.ttf"
            font = get_font_at_size(font_path, font_size)
            
            bbox = get_text_bbox(text_draw, text_course_length, font)
            text_width = bbox[2] - bbox[0]
            
            min_font_size = 10
            while text_width > 258 and font_size > min_font_size:
                font_size -= 1
                font = get_font_at_size(font_path, font_size)
                bbox = get_text_bbox(text_draw, text_course_length, font)
                text_width = bbox[2] - bbox[0]
            
            text_height = bbox[3] - bbox[1]
            x_pos_in_box = (260 - text_width) // 2
            y_pos_in_box = (60 - text_height) // 2 - bbox[1]
            
            text_draw.text(
                (x_pos_in_box, y_pos_in_box), 
                text_course_length, 
                fill="#1D1D1F", 
                font=font
            )
            
            img.paste(text_img, (1190, 600), text_img)
        except Exception as e:
            secure_log(f"Error processing course length: {e}", 'error')

    # ========================================================================
    # FIELD 5: SCORE
    # ========================================================================
    # Box: x=1005, y=888, w=126, h=67
    text_score = str(data.get('score', ''))
    
    if text_score:
        try:
            text_img = Image.new('RGBA', (126, 67), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_img)
            
            font_size = 38
            font_path = "Poppins-Regular.ttf"
            font = get_font_at_size(font_path, font_size)
            
            bbox = get_text_bbox(text_draw, text_score, font)
            text_width = bbox[2] - bbox[0]
            
            min_font_size = 10
            while text_width > 124 and font_size > min_font_size:
                font_size -= 1
                font = get_font_at_size(font_path, font_size)
                bbox = get_text_bbox(text_draw, text_score, font)
                text_width = bbox[2] - bbox[0]
            
            text_height = bbox[3] - bbox[1]
            x_pos_in_box = (126 - text_width) // 2
            y_pos_in_box = (67 - text_height) // 2 - bbox[1]
            
            text_draw.text(
                (x_pos_in_box, y_pos_in_box), 
                text_score, 
                fill="#1D1D1F", 
                font=font
            )
            
            img.paste(text_img, (1005, 888), text_img)
        except Exception as e:
            secure_log(f"Error processing score: {e}", 'error')

    # ========================================================================
    # FIELD 6: SIGNATURE IMAGE (CLOUD/LOCAL COMPATIBLE)
    # ========================================================================
    sig_box = {'x': 1157, 'y': 1076, 'w': 345, 'h': 110}
    signature_path = str(data.get('signature_image_path', ''))
    sig_img = None
    
    if signature_path:
        # Attempt 1: Fetch via centralized storage kernel (Cloud OR Local)
        # This handles GCS blob paths (e.g., "signatures/sig_123.png") automatically
        try:
            sig_content = download_file_content(signature_path)
            if sig_content:
                sig_img = Image.open(BytesIO(sig_content)).convert("RGBA")
        except Exception as e:
            secure_log(f"Error loading signature from storage: {e}", 'warning')

        # Attempt 2: Fallback to direct local filesystem (Legacy/Absolute Paths)
        if not sig_img and os.path.exists(signature_path):
            try:
                sig_img = Image.open(signature_path).convert("RGBA")
            except Exception as e:
                secure_log(f"Error loading local signature file: {e}", 'warning')

    if sig_img:
        try:
            sig_img.thumbnail((sig_box['w'], sig_box['h']), Image.Resampling.LANCZOS)
            
            sig_canvas = Image.new('RGBA', (sig_box['w'], sig_box['h']), (255, 255, 255, 0))
            sig_x = (sig_box['w'] - sig_img.width) // 2
            sig_y = (sig_box['h'] - sig_img.height) // 2
            
            sig_canvas.paste(sig_img, (sig_x, sig_y), sig_img)
            img.paste(sig_canvas, (sig_box['x'], sig_box['y']), sig_canvas)
        except Exception as e:
            secure_log(f"Error processing signature image: {e}", 'error')
    elif signature_path:
        secure_log(f"Signature image not found or unreadable: {signature_path}", 'warning')

    # ========================================================================
    # FIELD 7: CHANNEL NAME (BOTTOM) with Subscriber Count
    # ========================================================================
    chan_box = {'x': 1138, 'y': 1217, 'w': 395, 'h': 60}
    
    base_channel_name = str(data.get('channel_name', ''))
    subscriber_count = data.get('subscriber_count')
    subs_str = format_subscriber_count(subscriber_count)
    
    text_channel_name_bottom = f"{base_channel_name} {subs_str}".strip()
    
    if text_channel_name_bottom:
        try:
            text_img = Image.new('RGBA', (chan_box['w'], chan_box['h']), (255, 255, 255, 0))
            text_draw = ImageDraw.Draw(text_img)
            
            font_size = 28
            font_path = "Poppins-Regular.ttf"
            font = get_font_at_size(font_path, font_size)
            
            bbox = get_text_bbox(text_draw, text_channel_name_bottom, font)
            text_width = bbox[2] - bbox[0]
            
            min_font_size = 10
            while text_width > (chan_box['w'] - 2) and font_size > min_font_size:
                font_size -= 1
                font = get_font_at_size(font_path, font_size)
                bbox = get_text_bbox(text_draw, text_channel_name_bottom, font)
                text_width = bbox[2] - bbox[0]
            
            text_height = bbox[3] - bbox[1]
            x_pos_in_box = (chan_box['w'] - text_width) // 2
            y_pos_in_box = (chan_box['h'] - text_height) // 2 - bbox[1]
            
            text_draw.text(
                (x_pos_in_box, y_pos_in_box), 
                text_channel_name_bottom,
                fill="#1D1D1F", 
                font=font
            )
            
            img.paste(text_img, (chan_box['x'], chan_box['y']), text_img)
        except Exception as e:
            secure_log(f"Error processing channel name (bottom): {e}", 'error')

    # ========================================================================
    # FIELD 8: QR CODE
    # ========================================================================
    # Box: x=912, y=1038, w=217, h=217 (5% larger than original)
    qr_box = {'x': 912, 'y': 1038, 'w': 217, 'h': 217}
    qr_value = str(data.get('qr_code', ''))

    if qr_value:
        try:
            # Auto-detect base URL from request or use verification_base_url if provided
            if verification_base_url is None:
                base_url = get_base_url().rstrip('/')
                verification_url = f"{base_url}/verify_certificate/{qr_value}"
                secure_log(f"QR code URL (auto-detected): {verification_url}", 'info')
            else:
                verification_url = f"{verification_base_url}{qr_value}"

            qr = pyqrcode.create(verification_url, error='h')
            
            buffer = BytesIO()
            qr.png(
                buffer, 
                scale=8, 
                module_color="#FFFFFF",  # White modules
                background=None          # Transparent background
            )
            buffer.seek(0)
            
            qr_img = Image.open(buffer).convert('RGBA')
            qr_img = qr_img.resize((qr_box['w'], qr_box['h']), Image.Resampling.LANCZOS)
            img.paste(qr_img, (qr_box['x'], qr_box['y']), qr_img)
            
        except Exception as e:
            secure_log(f"Error generating QR code: {e}", 'error')
    
    # ========================================================================
    # SAVE AS PDF
    # ========================================================================
    # Generate output filename with pdf extension
    pdf_path = os.path.splitext(output_path)[0] + ".pdf"

    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        
        # Convert to RGB (PDFs don't support RGBA transparency)
        rgb_img = img.convert("RGB")
        
        # Save as PDF
        rgb_img.save(pdf_path, "PDF", resolution=100.0)
        
        secure_log(f"Certificate PDF generated: {pdf_path}", 'info')
        return pdf_path
        
    except Exception as e:
        secure_log(f"Error saving certificate PDF: {e}", 'error')
        return False
    

