# Contributing to SpendWise

Thank you for your interest in contributing to **SpendWise**! We welcome community contributions to help make personal expense tracking smarter, simpler, and more reliable.

---

## 🛠️ Development Setup

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/your-username/spendwise.git
   cd spendwise
   ```

2. **Set up a Virtual Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Or venv\Scripts\activate on Windows
   ```

3. **Install Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Environment Variables**:
   Copy `.env.example` to `.env` and set your optional `GEMINI_API_KEY`:
   ```bash
   cp .env.example .env
   ```

---

## 🧪 Testing Guidelines

Before opening a pull request, run the automated test suite to ensure all unit tests pass:

```bash
pytest tests/ -v
```

If you introduce new services or calculations, please add corresponding unit tests in `tests/test_services.py`.

---

## 📋 Pull Request Process

1. Create a descriptive feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Follow PEP 8 guidelines and write clean, readable code with docstrings where appropriate.
3. Commit with clear, conventional messages (e.g., `feat: ...`, `fix: ...`, `docs: ...`).
4. Ensure all tests pass.
5. Push your branch and open a Pull Request targeting `main`.

---

## 📄 License

By contributing to SpendWise, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).

