#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
chunk_generator.py - UPGRADED VERSION

Cloud Run Compatible with Centralized Logging
- Uses centralized secure_log() from __init__.py
- No local logger setup (all logging centralized)
- Optimized for 12K req/sec performance
- All existing functionality preserved
"""

import tiktoken
from chonkie import SentenceChunker
from typing import List

# Import centralized logging
from youcert import secure_log

# ============================================================================
# CONSTANTS
# ============================================================================

# Chunk size (80,000-100,000 tokens as requested)
DEFAULT_CHUNK_SIZE = 100000

# Overlap (500-1000 tokens as requested)
DEFAULT_OVERLAP = 1000

# Encoding for GPT-4o / GPT-5 class models
ENCODING_NAME = "o200k_base"

# Model name for encoding
MODEL_NAME = "gpt-4o"


# ============================================================================
# TRANSCRIPT CHUNKER CLASS
# ============================================================================

class TranscriptChunker:
    """
    Sentence-aware text chunker using chonkie library.
    
    Integrated with centralized logging system.
    Uses tiktoken (o200k_base) for accurate token counting.
    
    Features:
    - High-quality sentence boundary detection
    - Token-limited blocks for AI processing
    - Cloud Run compatible
    - Production-grade error handling
    """

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP):
        """
        Initialize the TranscriptChunker.

        Args:
            chunk_size (int): Target maximum tokens per chunk
            overlap (int): Target overlap tokens between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

        # Validate overlap
        if self.overlap >= self.chunk_size:
            secure_log(
                f"Overlap ({self.overlap}) >= chunk size ({self.chunk_size}). Adjusting to {self.chunk_size // 10}",
                'warning'
            )
            self.overlap = self.chunk_size // 10

        # Initialize tiktoken encoding
        try:
            self.encoding = tiktoken.get_encoding(ENCODING_NAME)
            secure_log(f"Initialized tiktoken encoding '{ENCODING_NAME}'", 'info')
        except Exception as e:
            secure_log(f"Failed to initialize tiktoken encoding '{ENCODING_NAME}': {e}", 'critical')
            raise

        # Initialize chonkie SentenceChunker
        try:
            self.chunker = SentenceChunker(
                tokenizer=self.encoding,
                chunk_size=self.chunk_size,
                chunk_overlap=self.overlap
            )
            secure_log(
                f"Initialized chonkie.SentenceChunker (Size: {self.chunk_size}, Overlap: {self.overlap})",
                'info'
            )
        except Exception as e:
            secure_log(f"Failed to initialize chonkie.SentenceChunker: {e}", 'critical')
            raise

    def chunk_text(self, text: str) -> List[str]:
        """
        Chunk large transcript using chonkie sentence-aware chunking.

        Args:
            text (str): Full, cleaned transcript text

        Returns:
            List[str]: List of text chunks
        """
        secure_log(
            f"Starting sentence-aware chunking (text length: {len(text)} chars)",
            'info'
        )
        
        # Validate input
        if not text or not text.strip():
            secure_log("Text for chunking is empty", 'warning')
            return []

        try:
            # Perform chunking
            chunks = self.chunker.chunk(text)
            secure_log(f"Chunking complete: {len(chunks)} chunks generated", 'info')
            return chunks
            
        except Exception as e:
            secure_log(f"Chunking error: {e}", 'error')
            
            # Fallback: return whole text as single chunk if small enough
            try:
                token_count = len(self.encoding.encode(text))
                if token_count <= self.chunk_size:
                    secure_log(
                        f"Fallback: using single chunk ({token_count} tokens)",
                        'warning'
                    )
                    return [text]
                else:
                    secure_log(
                        f"Text too large for single chunk ({token_count} tokens > {self.chunk_size})",
                        'error'
                    )
                    return []
            except Exception as fallback_error:
                secure_log(f"Fallback failed: {fallback_error}", 'error')
                return []


# ============================================================================
# MODULE TESTING (Development Only)
# ============================================================================

if __name__ == "__main__":
    """
    Test mode for development.
    This block only runs when executing this file directly.
    """
    import logging
    
    # Setup basic console logging for testing
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    print("\n" + "="*70)
    print("CHUNK GENERATOR TEST MODE")
    print("="*70 + "\n")
    
    # Initialize chunker with small limits for testing
    test_chunker = TranscriptChunker(chunk_size=30, overlap=10)
    
    # Sample text
    sample_text = (
        "This is the first sentence. It is short. "
        "This is the second sentence; it is a bit longer. "
        "This is the third sentence. Now for a fourth. "
        "And a fifth. The sixth sentence concludes this test."
    )
    
    # Chunk the text
    test_chunks = test_chunker.chunk_text(sample_text)
    
    # Print results
    print("\nCHUNKING RESULTS:")
    print("-" * 70)
    for i, chunk in enumerate(test_chunks):
        token_count = len(test_chunker.encoding.encode(chunk))
        print(f"\n[CHUNK {i+1}] ({token_count} tokens)")
        print(f"{chunk}")
    
    print("\n" + "="*70)
    print("TEST MODE FINISHED")
    print("="*70 + "\n")


    