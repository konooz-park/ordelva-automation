# ابدأ من هنا — ORDELVA-Automation

## التثبيت (مرة واحدة)
1. فكّ الضغط إلى: `Documents\ORDELVA-Automation`
2. افتح PowerShell داخل المجلد ونفّذ:
   ```
   powershell -ExecutionPolicy Bypass -File windows\setup.ps1
   ```
   السكربت يفحص الجهاز (المعالج، الذاكرة، المساحة، كرت الشاشة، CUDA) ويحفظ النتيجة في `system_report.json`.
   بعدها يثبّت Python وFFmpeg، ويسألك قبل كل تثبيت.
   ثم يحمّل نموذج الصوت ويتحقق منه ببصمة SHA-256، ويختار نموذج Ollama المناسب للجهاز.
   في النهاية يعيد إنتاج فيديو Doggerland ليتأكد أن كل شيء يعمل.

## بعد إعادة تشغيل الكمبيوتر
لا يوجد شيء يجب تشغيله في الخلفية. افتح المجلد وانقر مرتين على `start_dashboard.bat` لتفتح لوحة التحكم على http://127.0.0.1:8765

## إنتاج فيديو جديد
```
ordelva.bat ideas --n 10
ordelva.bat draft <id> "<Wikipedia title>" --title "<عنوان الفيديو>"
   (راجع ملف projects\<id>\spec.json وصحّح الحقائق)
ordelva.bat media <id>
ordelva.bat render <id>
   (شاهد الفيديو، ثم ضع علامة على بنود المراجعة الخمسة في لوحة التحكم واضغط Approve)
ordelva.bat auth          (ربط القناة عبر OAuth الرسمي، مرة واحدة)
ordelva.bat upload <id>   (يُرفع خاصًا Private افتراضيًا)
```

## ضوابط الأمان
- الإنتاج الآلي مُطفأ (`production_enabled=false`) حتى توافق على الجودة.
- لا يمكن النشر العام إلا إذا غيّرت أنت `allow_public_publish` إلى true.
- الرموز السرية تُحفظ في `%LOCALAPPDATA%\ORDELVA` وليس داخل المشروع.
