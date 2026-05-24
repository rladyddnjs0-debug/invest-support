import logging
import os
from datetime import datetime

def setup_logger(name="invest_support"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    
    # 로그 디렉토리 생성
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # 파일 핸들러 (상세 로그, 날짜별 저장)
    file_name = f"logs/invest_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(file_name, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # 콘솔 핸들러 (간결한 로그)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 기본 로거 인스턴스 생성
logger = setup_logger()
