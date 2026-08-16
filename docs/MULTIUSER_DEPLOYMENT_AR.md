# نشر Telegram MCP متعدد المستخدمين على Ubuntu

## المتطلبات

يحتاج الخادم إلى Python 3.11 أو أحدث، اسم نطاق HTTPS ثابت، وبيئة Python. Quick Tunnel مناسب للاختبار فقط؛ للاستخدام مع عدة مستخدمين استخدم نطاقًا ثابتًا وشهادة HTTPS مستقرة أو Cloudflare Tunnel مُدارًا.

## متغيرات البيئة

انسخ `.env.multi.example` إلى `.env.multi` وأدخل قيم التطبيق. لا تضع جلسات Telegram داخل الملف؛ الجلسات تُنشأ بعد ربط المستخدم وتُخزن مشفّرة في قاعدة البيانات.

يتطلب `MCP_INVITE_CODES` JSON يربط كل دعوة بمستخدم داخلي. مثال تطوير:

```json
{"invite-user-a":"user-a","invite-user-b":"user-b"}
```

لا تستخدم رموزًا قصيرة أو متوقعة في الإنتاج، ولا تشارك الرمز في قنوات عامة.

## التشغيل

```bash
cd /home/work/telegram-mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python multi_http.py
```

اضبط `MCP_HOST=127.0.0.1` و`MCP_PORT=8080`. يجب أن يمرر reverse proxy المسار `/mcp` إلى `http://127.0.0.1:8080/mcp`، مع إبقاء buffering معطلاً ومهلة streaming طويلة. لا تعرض المنفذ الداخلي مباشرةً إذا كان النفق أو reverse proxy هو طبقة الوصول.

## systemd

أنشئ خدمة مخصصة للمستخدم أو root حسب سياسة التشغيل، وضع الأسرار في ملف محمي أو secret manager، ثم استخدم `Restart=on-failure` أو `Restart=always` مع حدود للذاكرة وسجل journal محدود الدوران. يجب تشغيل عملية MCP وعملية النفق كخدمتين منفصلتين، مع healthcheck ومراقبة.

## Cloudflare أو reverse proxy

يجب أن يكون `MCP_PUBLIC_BASE_URL` هو الأصل العام الثابت، مثل:

```text
https://mcp.example.com
```

وليس عنوان VNC أو رابط Quick Tunnel مؤقتًا. اضبط:

```text
MCP_ALLOWED_HOSTS=mcp.example.com
MCP_ALLOWED_ORIGINS=https://mcp.example.com
```

ثم استخدم:

```text
https://mcp.example.com/mcp
```

في Gemini. يجب اختبار `/.well-known/oauth-authorization-server` و`/.well-known/oauth-protected-resource/mcp` من خارج الخادم.

## مسار المستخدم

يضيف المستخدم رابط MCP في Gemini، يكمل OAuth، ثم يطلب `tg_connect_telegram`. يفتح رابط الربط الخاص، يدخل رقم Telegram، ثم رمز Telegram و2FA في صفحة HTTPS. بعد نجاح الربط يعود إلى Gemini ويستخدم `tg_account_overview` أو أدوات القراءة.

## النسخ الاحتياطي

في MVP احمِ ملف SQLite ومفتاح Fernet معًا في مكانين منفصلين؛ لا فائدة من نسخة قاعدة البيانات وحدها إذا فُقد مفتاح التشفير، ولا يجوز تخزين المفتاح بجانب النسخة. في الإنتاج انقل البيانات الوصفية إلى PostgreSQL والجلسات إلى Vault/KMS، واختبر استعادة نسخة مشفرة وإبطال الجلسات.

## قائمة فحص قبل فتح الرابط

| الفحص | المطلوب |
|---|---|
| HTTPS | شهادة صحيحة ونطاق ثابت |
| OAuth | PKCE وredirect URI مضبوط وscopes محددة |
| العزل | مستخدمان لا يستطيع أحدهما قراءة جلسة الآخر |
| الجلسات | ciphertext فقط في قاعدة البيانات |
| السجلات | لا رموز ولا كلمات مرور ولا StringSession |
| Telegram | حدود معدل ومعالجة FloodWait |
| العمليات الحساسة | تأكيد وتدقيق قبل الإرسال أو الإبطال |
| النشر | إعادة تشغيل تلقائي وhealthcheck ونسخ احتياطي |
