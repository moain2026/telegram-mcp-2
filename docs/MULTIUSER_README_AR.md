# Telegram MCP متعدد المستخدمين — نسخة MVP

هذه النسخة تجعل رابط MCP واحدًا يخدم عدة مستخدمين، لكن كل مستخدم يحصل على جلسة Telegram مستقلة ومشفّرة. لا توجد جلسة Telegram عامة مشتركة بين المستخدمين.

## كيف يعمل التدفق؟

1. يتصل المستخدم بخادم MCP عبر OAuth/PKCE.
2. يحصل الخادم على `subject` مستقل للمستخدم.
3. يستدعي المستخدم الأداة `tg_connect_telegram`.
4. تعيد الأداة رابطًا قصير العمر خاصًا بهذا المستخدم.
5. يفتح المستخدم الرابط في المتصفح ويدخل رقم Telegram بنفسه.
6. يدخل رمز Telegram في الصفحة، ثم كلمة مرور 2FA إذا طلبت Telegram ذلك.
7. تحفظ الخدمة StringSession مشفّرة وترتبط بسجل المستخدم.
8. كل أداة لاحقة تحمل هوية OAuth نفسها وتستخدم جلسة المستخدم نفسه فقط.

لا تضع رمز Telegram أو كلمة مرور 2FA في Gemini أو في عنوان URL أو في السجلات.

## الإعداد المحلي

انسخ `.env.multi.example` إلى `.env.multi` ثم عيّن `TELEGRAM_API_ID` و`TELEGRAM_API_HASH` ومفتاح Fernet عشوائيًا. في نسخة MVP يحدد `MCP_INVITE_CODES` هوية المستخدم بعد OAuth، مثل:

```json
{"invite-user-a":"user-a","invite-user-b":"user-b"}
```

كل رمز دعوة يجب أن يكون مختلفًا. هذا بديل مؤقت لشاشة OIDC/SSO حقيقية؛ في الإنتاج استبدله بموفر هوية مؤسسي.

ثبت الاعتماديات ثم شغّل:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python multi_http.py
```

يستمع الخادم عادةً على `127.0.0.1:8080` ومسار MCP هو `/mcp`.

## الأدوات الأساسية

| الأداة | الوظيفة | النطاق |
|---|---|---|
| `tg_connection_status` | حالة ربط المستخدم بحساب Telegram | قراءة |
| `tg_connect_telegram` | إنشاء رابط ربط خاص قصير العمر | قراءة/إعداد |
| `tg_unlink_telegram` | إبطال جلسة المستخدم | تأكيد مطلوب |
| `tg_status` | معلومات الحساب المرتبط دون كشف الرقم الكامل | `telegram:read` |
| `tg_account_overview` | مجموعات وقنوات ومستخدمو ذلك الحساب في نتيجة واحدة | `telegram:read` |
| `tg_list_dialogs` | قائمة المحادثات الخاصة بالمستخدم | `telegram:read` |
| `tg_get_dialog_details` | تفاصيل محادثة | `telegram:read` |
| `tg_read_messages` | قراءة الرسائل | `telegram:read` |
| `tg_search_messages` | البحث في رسائل الحساب | `telegram:read` |
| `tg_resolve` | حل اسم أو رابط Telegram | `telegram:read` |
| `tg_send_message` | إرسال رسالة | `telegram:send` + `confirm=true` |
| `tg_download_media` | تنزيل وسائط إلى مجلد خاص بالمستخدم | `telegram:media` |

## ربط Gemini

أضف رابط HTTPS العام إلى تطبيق Gemini المخصص. يجب أن يوجه الرابط إلى `/mcp`، مثل:

```text
https://mcp.example.com/mcp
```

بعد المزامنة، يبدأ Gemini OAuth. عند نجاح الاتصال جرّب:

```text
اعرض حالة اتصال Telegram الخاصة بي.
```

ثم:

```text
استخدم tg_connect_telegram وأنشئ رابط ربط خاصًا بي.
```

افتح الرابط في المتصفح وأكمل رقم الهاتف والرمز و2FA هناك. بعد ظهور `active` في `tg_connection_status` جرّب `tg_account_overview`.

## العزل

لا تقبل الأدوات `tenant_id` أو `telegram_session_id` من النموذج أو المستخدم بوصفهما مصدر الحقيقة. الخادم يستخرج `subject` من access token، ثم يبحث عن حساب Telegram المرتبط به. تحفظ الجلسة داخل SQLite في MVP بعد تشفيرها بـFernet. عند الإنتاج استخدم PostgreSQL وVault/KMS، ولا تعتمد على SQLite أو مفتاح ثابت داخل ملف البيئة.

## حدود هذه النسخة

هذه MVP وليست منصة SaaS مكتملة. نظام الدعوة الحالي يربط invite code بمستخدم ثابت بدل OIDC/SSO كامل. التخزين SQLite مناسب لمضيف واحد فقط. لا يوجد في هذه النسخة تسجيل جماعي أو إضافة أعضاء أو حذف رسائل أو تنفيذ Telegram method عام. يجب إضافة rate limits، مراقبة، نسخ احتياطية مشفرة، اختبار اختراق، ومزود هوية مؤسسي قبل مشاركة الرابط مع جمهور واسع.

## اختبار الجودة

من جذر المشروع:

```bash
.venv/bin/pytest -q tests
```

الاختبارات الحالية تغطي تشفير الجلسة، عزل مستخدمين، توكنات OAuth، انتهاء روابط الربط، تحميل الخادم، وظهور الأدوات.
