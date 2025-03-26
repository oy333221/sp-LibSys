import requests
import time
import logging
from datetime import datetime
import os
from dotenv import load_dotenv

# 設置日誌
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("keep_alive.log"),
        logging.StreamHandler()
    ]
)

# 載入環境變數
load_dotenv()

# 從環境變數獲取URL，如果沒有則使用預設值
APP_URL = os.environ.get('APP_URL', 'https://your-app-url.onrender.com')
INTERVAL_MINUTES = int(os.environ.get('PING_INTERVAL', 10))

def ping_app():
    """向應用程式發送請求，維持服務運作"""
    try:
        start_time = time.time()
        response = requests.get(APP_URL, timeout=30)
        end_time = time.time()
        
        if response.status_code == 200:
            logging.info(f"成功喚醒 ({response.status_code}), 回應時間: {end_time - start_time:.2f}秒")
        else:
            logging.warning(f"喚醒時出現非預期的回應: {response.status_code}")
            
    except requests.RequestException as e:
        logging.error(f"喚醒失敗: {str(e)}")

def main():
    """主程序，定期執行ping操作"""
    logging.info(f"啟動服務喚醒程式 - 目標URL: {APP_URL}")
    logging.info(f"喚醒間隔: {INTERVAL_MINUTES}分鐘")
    
    try:
        while True:
            ping_app()
            # 間隔時間 (秒)
            sleep_time = INTERVAL_MINUTES * 60
            logging.debug(f"等待{INTERVAL_MINUTES}分鐘後再次喚醒...")
            time.sleep(sleep_time)
    except KeyboardInterrupt:
        logging.info("程式手動停止")
    except Exception as e:
        logging.critical(f"發生未預期的錯誤: {str(e)}")
        
if __name__ == "__main__":
    main() 