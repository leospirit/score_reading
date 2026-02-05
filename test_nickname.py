
from pathlib import Path
import re

def _extract_nickname(student_id: str) -> str:
    """
    Extract nickname from filename/student_id.
    Rule: Take first 3 chars. 
      - If 3rd char is non-Chinese (e.g. digit), take first 2.
      - If 3rd char is Chinese, take last 2 (index 1-2).
      - Fallback: use full string if short.
    """
    if not student_id:
        return "同学"
        
    stem = student_id.split('.')[0]
    
    if len(stem) < 2:
        return stem
        
    prefix = stem[:3]
    if len(prefix) < 3:
        return prefix
        
    third_char = prefix[2]
    
    is_chinese = '\u4e00' <= third_char <= '\u9fff'
    
    print(f"Input: {student_id}, Prefix: {prefix}, 3rd: {third_char}, Chinese: {is_chinese}")

    if is_chinese:
        # Likely a 3-char name or longer -> "恩齐"
        return prefix[1:3]
    else:
        # Likely 2-char name + digit/suffix -> "乘月"
        return prefix[:2]

test_cases = [
    "郭雨鑫6单元背诵.mp3",
    "郭雨鑫_v1.mp3",
    "崔恩齐.wav",
    "李明.mp3",
    "Tom.mp3",
    "Alice_Task1",
    "web_20260203_abc",
    "张三_v2"
]

for t in test_cases:
    print(f"'{t}' -> '{_extract_nickname(t)}'")
