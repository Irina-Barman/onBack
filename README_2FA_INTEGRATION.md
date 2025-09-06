
# 2FA (Google Authenticator) интеграция в Onfine

## ENV
Добавьте в `.env`:
```env
SECURITY_FERNET_KEY=dev-fernet-key-32bytes________
TOTP_ISSUER=Onfine
TOTP_WINDOW=1
TMP_TOKEN_EXPIRES=600
```
Для продакшена сгенерируйте 32 байта и задайте base64 urlsafe ключ (44 символа).

## Эндпоинты (JWT обязателен)
- POST `/auth/2fa/setup` → `{ otpauth_url, qr_data_url }`
- GET  `/auth/2fa/qr.png` → PNG
- POST `/auth/2fa/enable` { code }
- POST `/auth/2fa/verify` { code }
- POST `/auth/2fa/backup/generate`
- POST `/auth/2fa/backup/use` { backup_code }
- POST `/auth/2fa/disable`

## Поток логина
1) После логина паролем проверяйте `user.is_2fa_enabled`.
2) Если включена — требуйте отдельный шаг `/auth/2fa/verify` до выдачи «чувствительных» действий.
3) Либо включите 2FA в выдачу токена в вашем `AuthService.login`: при `is_2fa_enabled` требуйте код.
