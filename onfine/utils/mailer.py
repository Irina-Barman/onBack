def send_email(to: str, subject: str, body: str):
    """
    Пока просто выводим письмо в консоль.
    Замените на Flask-Mail или любой SMTP-клиент.
    """
    print(f"[MAIL] To:{to}  Subj:{subject}\n{body}\n")
