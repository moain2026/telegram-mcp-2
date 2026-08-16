# دليل الأمان متعدد المستخدمين

## نموذج الثقة

رابط MCP واحد لا يعني حساب Telegram واحدًا. كل access token يحمل `subject` للمستخدم، وكل أداة تستخرج هذا subject من سياق المصادقة بدل قبول `user_id` من مدخلات Gemini. بعدها تُفتح جلسة Telegram المرتبطة بذلك subject فقط.

## الجلسات

StringSession سرّ قابل لاستخدام حساب Telegram. لذلك تُحفظ مشفّرة بـFernet قبل SQLite، ولا تظهر في استجابة الأدوات أو السجلات أو عناوين URL. يجب وضع مفتاح Fernet في secret manager. فقدان المفتاح يعني فقدان القدرة على فك الجلسات؛ تسريب المفتاح يعني تدوير كل الجلسات.

## تسجيل الدخول

يتم إدخال رقم الهاتف ورمز Telegram و2FA في صفحة HTTPS قصيرة العمر، لا داخل Gemini. رابط الربط يحمل token عشوائيًا منتهي الصلاحية ويُستخدم لمسار مستخدم واحد. لا تحفظ الصفحة الرموز بعد الطلب ولا تعرضها في HTML أو logs.

## OAuth

النسخة تستخدم Authorization Code مع PKCE، access tokens قصيرة العمر، refresh token rotation، scopes، وإبطال token. استبدل invite-code MVP بموفر OIDC/SSO قبل فتح الخدمة لجمهور عام.

## العزل

لا تستخدم مسارًا أو اسم ملف أو chat ID من مستخدم آخر. يجب أن تكون مسارات التنزيل داخل `data/downloads/<subject>`، وأن تكون الاستعلامات محددة بالـsubject، وأن لا تكون الجلسة أو كائن TelegramClient متغيرًا عالميًا مشتركًا.

## الأدوات الحساسة

الإرسال والإبطال والعمليات المستقبلية مثل الحذف والإضافة يجب أن تتطلب scope مناسبًا وconfirm صريحًا. لا تضف `execute_method` عامًا. لا تمنح scopes الإرسال والإدارة افتراضيًا للمستخدم الجديد.

## النشر

استخدم نطاق HTTPS ثابتًا، HSTS، reverse proxy أو Cloudflare Access، rate limits، سجلات تدقيق بلا أسرار، نسخًا احتياطية مشفرة، مراقبة FloodWait، وتدويرًا دوريًا للمفاتيح. Quick Tunnel صالح للاختبار وليس ضمانًا لتشغيل 24/7.

## حظر التسريب

يجب أن يبقى خارج Git والمرفقات: `.env`، `.env.multi`، StringSession، SQLite الإنتاجية، مفاتيح Fernet، رموز OAuth، رموز GitHub، رمز VNC، OTP و2FA. راجع `git diff --cached` و`git grep` قبل كل push.
