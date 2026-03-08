# موسوعة الأخلاق — مُصدَّرة

تصدير آلي لـ [موسوعة الأخلاق](https://dorar.net/alakhlaq) من موقع الدرر السنية بصيغتي **EPUB** و**Markdown**.

---

## الملفات

```
.
├── dorar_export.py          # السكريبت الرئيسي
├── requirements.txt
├── .github/workflows/
│   └── export.yml           # GitHub Actions
└── output/
    ├── alakhlaq.epub        # ملف EPUB
    └── md/                  # Markdown مُهيكل
        └── [باب]/
            ├── _index.md
            └── [فصل]/
                ├── _index.md
                └── [مبحث]/
                    ├── _index.md
                    └── NNNNN_عنوان.md
```

---

## التشغيل المحلي

```bash
pip install -r requirements.txt

# كامل
python dorar_export.py

# اختبار (10 صفحات فقط)
TEST_PAGES=10 python dorar_export.py
```

الناتج في مجلد `output/`.

---

## GitHub Actions

الـ workflow يعمل يدوياً من تبويب **Actions**:

1. اضغط **Run workflow**
2. أدخل عدد صفحات للاختبار (أو اتركه `0` للكامل)
3. بعد الانتهاء يُعمل commit تلقائي بالناتج

---

## المتطلبات

- Python 3.11+
- `requests`, `beautifulsoup4`, `lxml`
