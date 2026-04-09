@echo off
echo Starting SHUBHAM NX Billing App...
echo.
echo Window 1 = Flask server (keep this open)
echo Window 2 = Cloudflare tunnel (your public URL will appear here)
echo.
start "Flask Server" cmd /k "python app.py"
timeout /t 3 /nobreak >nul
start "Cloudflare Tunnel" cmd /k "cloudflared.exe tunnel --url http://localhost:8081"
echo.
echo Both windows are opening...
echo Look at the Cloudflare window for your public URL (ends in trycloudflare.com)
echo Share that URL with any device to access the billing app.
pause
