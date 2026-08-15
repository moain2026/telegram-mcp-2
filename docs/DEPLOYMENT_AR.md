# دليل النشر على Ubuntu السحابي

## المتطلبات

يحتاج الخادم إلى Ubuntu، Python 3.11 أو أحدث، Git أو نسخة من ملفات المشروع، بيئة Python افتراضية، متغيرات Telegram API في `.env`، وعملية نفق HTTPS أو Reverse Proxy دائم.

## 1. تجهيز المشروع

```bash
mkdir -p /home/work/telegram-mcp
cd /home/work/telegram-mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install 'mcp<2'
```

تم تثبيت سلسلة MCP من الإصدار 1.x لأن النسخة الأصلية من المشروع تعتمد على واجهات FastMCP المتوافقة معها.

## 2. ملف البيئة

أنشئ ملفًا محليًا باسم `.env` بصلاحية `600`، ولا تضعه في Git أو داخل ملف ZIP:

```dotenv
TELEGRAM_API_ID=ضع_القيمة_محليًا
TELEGRAM_API_HASH=ضع_القيمة_محليًا
TELEGRAM_SESSION=ضع_جلسة_Telegram_محليًا
TELEGRAM_DOWNLOAD_DIR=/home/work/telegram-mcp/downloads
```

لا تضع رقم الهاتف أو كلمة مرور 2FA أو رمز تسجيل الدخول داخل المستودع. الجلسة هي سر دخول فعلي للحساب ويجب معاملتها مثل كلمة المرور.

## 3. تشغيل Streamable HTTP

يستخدم الملف `http_server_cloud.py` كغلاف لتشغيل الخادم على العنوان الداخلي `127.0.0.1:8080` والمسار `/mcp`:

```bash
cd /home/work/telegram-mcp
chmod 600 .env
nohup env MCP_HOST=127.0.0.1 \
  MCP_PORT=8080 \
  MCP_PUBLIC_HOST=your-public-host.example \
  .venv/bin/python -u http_server_cloud.py \
  >/tmp/telegram-mcp.log 2>&1 &
```

## 4. HTTPS دائم

للاستخدام الدائم يفضّل وضع Nginx أو Cloudflare Tunnel مُدار أمام الخادم. يجب أن يمرر المسار `/mcp` إلى `http://127.0.0.1:8080/mcp`، وأن يدعم الاتصالات طويلة المدة و`text/event-stream`، وأن يضيف النطاق العام إلى قائمة Host المسموحة في `TransportSecuritySettings`.

لا تستخدم Quick Tunnel المؤقت إلا للاختبار؛ لأن الرابط يتغير أو يتوقف عند انتهاء العملية أو إعادة تشغيل السحابة.

## 5. فحص الخدمة

```bash
curl -i https://your-public-host.example/mcp
```

الاستجابة المتوقعة لطلب GET غير المهيأ قد تكون `406` وتطلب قبول `text/event-stream`، وهذا طبيعي. الاختبار الفعلي يكون عبر طلب MCP `initialize`:

```bash
curl -i -X POST https://your-public-host.example/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"preflight","version":"1.0"}}}'
```

بعد ذلك اختبر `tools/list` ثم أداة قراءة مثل `tg_status`. لا تختبر الإرسال أو الحذف تلقائيًا.
