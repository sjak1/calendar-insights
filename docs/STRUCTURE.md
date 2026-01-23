# Repository Structure

## 📁 Directory Organization

```
calender-insights/
├── seed/                    # EBD seeding scripts
│   ├── seed_ebd.py
│   ├── seed_ebd_apple.py
│   └── seed_ebd_phillips66.py
│
├── documents/               # Document storage
│   └── ebd/                # Executive Briefing Documents (EBDs)
│       ├── EBD_Apple_FILLED.pptx
│       ├── EBD_Amazon_FILLED.pptx
│       ├── EBD_Phillips66_FILLED.pptx
│       ├── EBD_Dell_Unstructured.pdf
│       └── ...
│
├── docs/                    # Documentation files
│   ├── AGENDA_GENERATOR.md
│   ├── AGENDA_GENERATION_FLOW.md
│   ├── TODO.md
│   └── ...
│
├── tools/                   # Core tool modules
│   ├── agenda_generator.py
│   ├── extract_ebd.py
│   ├── handlers.py
│   └── ...
│
├── scripts/                 # Utility scripts
├── utils/                   # Utility modules
├── data/                    # Data files
├── logs/                    # Log files
├── misc/                    # Miscellaneous files
└── static/                  # Static web assets
```

## 🔧 Usage

### Running Seed Scripts
```bash
# Generate EBD for a company
python seed/seed_ebd_apple.py
python seed/seed_ebd_phillips66.py
```

### Accessing EBD Documents
```python
# In code
ebd_path = "documents/ebd/EBD_Apple_FILLED.pptx"
```

## 📝 Notes

- All EBD documents (PPTX/PDF) are in `documents/ebd/`
- Seed scripts generate EBDs and save them to `documents/ebd/`
- Documentation is centralized in `docs/`
- Core tools remain in `tools/`

