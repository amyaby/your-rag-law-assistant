from app.core.llm import generate_answer

q = "What time does the main library close on Fridays?"
c = "The university main library is open Monday through Thursday from 8 AM to 10 PM. On Fridays, it closes early at 6 PM. It is closed on weekends."

answer = generate_answer(q, c)
print("Question:", q)
print("Answer:", answer)
