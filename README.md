# Library System

## 安全設置

為了保護敏感資訊，本專案使用環境變數來存儲敏感配置。在啟動專案前請遵循以下步驟：

1. 安裝所需套件：
```
pip install -r requirements.txt
```

2. 創建 `.env` 檔案並填入以下資訊：
```
FLASK_SECRET_KEY=your_secure_secret_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
ADMIN_PASSWORD=your_admin_password
```

**警告：** 請勿將 `.env` 檔案或其中的敏感資訊提交到版本控制系統（如 GitHub）！

## 部署注意事項

1. 在生產環境中，請確保：
   - 使用強密碼
   - 設置適當的 CORS 限制
   - 啟用 HTTPS
   - 定期輪換密鑰

2. Supabase 安全性建議：
   - 使用更精細的行級安全策略 (RLS)
   - 限制不必要的 API 權限
   - 監控資料庫活動

## 開發說明

開發時請遵循以下最佳實踐：

1. 不要在程式碼中硬編碼敏感資訊
2. 使用參數化查詢防止SQL注入
3. 驗證所有用戶輸入

## 啟動應用

```
python app.py
``` 