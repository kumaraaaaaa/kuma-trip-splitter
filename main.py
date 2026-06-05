import httpx
import random
import string
import os
from typing import List

from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from dotenv import load_dotenv
from passlib.context import CryptContext

import models

# 密碼雜湊設定 (使用 bcrypt 演算法)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

load_dotenv()
# 自動建立資料表結構與連線
DATABASE_URL = os.getenv(
    "DATABASE_URL"
)

# 處理 Supabase 網址相容性 (SQLAlchemy 需要 postgresql:// 開頭)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite 需要 check_same_thread，Supabase (PostgreSQL) 不需要
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="🧸 小熊旅費拆帳")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# ==============================
# Pydantic Schemas (資料驗證)
# ==============================
class AuthData(BaseModel):
    username: str
    password: str

class PaymentDetail(BaseModel):
    user_id: int
    amount_paid: float

class SplitDetail(BaseModel):
    user_id: int
    amount_owed: float

class ExpenseCreate(BaseModel):
    description: str
    currency: str
    exchange_rate: float
    amount: float 
    consumption_date: str
    consumption_time: str
    payments: List[PaymentDetail]
    splits: List[SplitDetail]

class RepaymentCreate(BaseModel):
    sender_id: int
    receiver_id: int
    amount: float

# ==============================
# 認證系統 (Auth API)
# ==============================
@app.post("/auth/register")
def register(data: AuthData, db: Session = Depends(get_db)):
    if db.query(models.AppUser).filter(models.AppUser.username == data.username).first():
        raise HTTPException(400, "該帳號已被註冊！")
        
    # 將密碼轉換為雜湊值後再存入資料庫，不儲存明文
    hashed_pwd = get_password_hash(data.password)
    u = models.AppUser(username=data.username, password=hashed_pwd)
    
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id, "username": u.username}

@app.post("/auth/login")
def login(data: AuthData, db: Session = Depends(get_db)):
    u = db.query(models.AppUser).filter(models.AppUser.username == data.username).first()
    
    # 驗證帳號是否存在，以及「使用者輸入的密碼」與「資料庫內的雜湊值」是否吻合
    if not u or not verify_password(data.password, u.password):
        raise HTTPException(400, "帳號或密碼錯誤！")
        
    return {"id": u.id, "username": u.username}

# ==============================
# 路由系統
# ==============================
@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("index.html", encoding="utf-8") as f: return f.read()

@app.get("/get-rate/{currency}")
async def get_live_rate(currency: str):
    if currency == "TWD": return {"rate": 1.0}
    url = "https://open.er-api.com/v6/latest/TWD"
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url); data = res.json()
            if data.get("result") == "success":
                rate = 1 / data['rates'][currency]
                return {"rate": round(rate, 5)}
            return {"rate": 1.0}
        except: return {"rate": 1.0}

# --- 行程管理 (加入邀請碼與帳戶綁定) ---
@app.get("/trips")
def get_trips(x_user_id: int = Header(None), db: Session = Depends(get_db)):
    if not x_user_id: raise HTTPException(401, "請先登入")
    u = db.query(models.AppUser).filter(models.AppUser.id == x_user_id).first()
    return u.trips if u else []

@app.post("/trips")
def create_trip(title: str, x_user_id: int = Header(None), db: Session = Depends(get_db)):
    if not x_user_id: raise HTTPException(401, "請先登入")
    u = db.query(models.AppUser).filter(models.AppUser.id == x_user_id).first()
    
    # 產生不重複的6碼邀請碼
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    while db.query(models.Trip).filter(models.Trip.invite_code == code).first():
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
    t = models.Trip(title=title, invite_code=code)
    t.app_users.append(u)
    db.add(t); db.commit(); db.refresh(t)
    return {"id": t.id, "title": t.title, "invite_code": t.invite_code}

@app.post("/trips/join")
def join_trip(code: str, x_user_id: int = Header(None), db: Session = Depends(get_db)):
    if not x_user_id: raise HTTPException(401, "請先登入")
    u = db.query(models.AppUser).filter(models.AppUser.id == x_user_id).first()
    t = db.query(models.Trip).filter(models.Trip.invite_code == code.upper()).first()
    if not t: raise HTTPException(404, "找不到此邀請碼對應的行程！")
    
    if t not in u.trips:
        u.trips.append(t)
        db.commit()
    return {"status": "success"}

@app.delete("/trips/{trip_id}")
def delete_trip(trip_id: int, db: Session = Depends(get_db)):
    # 1. 先確認有沒有這趟行程
    trip = db.query(models.Trip).filter(models.Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="找不到此行程")

    try:
        # 2. 依序手動刪除所有「依附在這趟行程底下」的關聯資料
        # (注意：必須先刪除最底層的明細，再刪除主檔)
        
        db.execute(text("DELETE FROM user_trips WHERE trip_id = :trip_id"), {"trip_id": trip_id})
        
        # 刪除還款紀錄 (repayments)
        db.query(models.Repayment).filter(models.Repayment.trip_id == trip_id).delete()

        # 刪除這趟行程的所有花費 (這會連動刪除 expense_payments 跟 expense_splits，前提是你的 Expense model 刪除正常)
        # 為了保險起見，我們先把花費撈出來，逐一刪除
        expenses = db.query(models.Expense).filter(models.Expense.trip_id == trip_id).all()
        for e in expenses:
            db.query(models.ExpensePayment).filter(models.ExpensePayment.expense_id == e.id).delete()
            db.query(models.ExpenseSplit).filter(models.ExpenseSplit.expense_id == e.id).delete()
            db.delete(e)

        # 刪除旅伴名單 (users)
        db.query(models.User).filter(models.User.trip_id == trip_id).delete()

        # 3. 障礙物都清空了，現在可以安全刪除行程本身了！
        db.delete(trip)
        db.commit()
        return {"status": "success", "message": "行程與相關資料已徹底刪除"}

    except Exception as e:
        # 如果發生任何錯誤，就還原資料庫狀態，避免刪除到一半
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# --- 旅伴管理 ---
@app.get("/trips/{trip_id}/users")
def get_trip_users(trip_id: int, db: Session = Depends(get_db)):
    return db.query(models.User).filter(models.User.trip_id == trip_id).all()

@app.post("/trips/{trip_id}/users")
def create_trip_user(trip_id: int, name: str, db: Session = Depends(get_db)):
    new_user = models.User(name=name, trip_id=trip_id)
    db.add(new_user); db.commit(); db.refresh(new_user)
    return new_user

@app.put("/users/{user_id}")
def update_user(user_id: int, name: str, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.id == user_id).first()
    if u: 
        u.name = name; db.commit()
    return u

@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.id == user_id).first()
    if u: 
        u.is_active = False; db.commit()
    return {"status": "ok"}

@app.put("/users/{user_id}/restore")
def restore_user(user_id: int, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.id == user_id).first()
    if u: 
        u.is_active = True; db.commit()
    return {"status": "ok"}

# --- 帳目管理 ---
@app.post("/expenses")
def create_expense(exp: ExpenseCreate, trip_id: int, db: Session = Depends(get_db)):
    # 建立花費主檔
    new_exp = models.Expense(
        trip_id=trip_id, amount=exp.amount, currency=exp.currency,
        exchange_rate=exp.exchange_rate, description=exp.description,
        consumption_date=exp.consumption_date, 
        consumption_time=exp.consumption_time
    )
    db.add(new_exp); db.commit(); db.refresh(new_exp)

    # 寫入代墊者與分攤者明細 (一對多關聯)
    for p in exp.payments: db.add(models.ExpensePayment(expense_id=new_exp.id, user_id=p.user_id, amount_paid=p.amount_paid))
    for s in exp.splits: db.add(models.ExpenseSplit(expense_id=new_exp.id, debtor_id=s.user_id, amount_owed=s.amount_owed))
    db.commit()
    return {"status": "success"}

@app.get("/expenses/{expense_id}")
def get_expense_detail(expense_id: int, db: Session = Depends(get_db)):
    # 尋找特定 ID 的花費主檔
    e = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not e: raise HTTPException(status_code=404)
    # 將主檔與其一對多的關聯明細 (payments, splits) 獨立打包回傳
    return {
        "description": e.description, 
        "amount": e.amount, 
        "currency": e.currency, 
        "exchange_rate": e.exchange_rate, 
        "date": e.consumption_date, 
        "time": e.consumption_time,
        "payments": [{"user_id": p.user_id, "amount": p.amount_paid} for p in e.payments],
        "splits": [{"user_id": s.debtor_id, "amount": s.amount_owed} for s in e.splits]
    }

@app.put("/expenses/{expense_id}")
def update_expense(expense_id: int, exp: ExpenseCreate, db: Session = Depends(get_db)):
    e = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not e: raise HTTPException(status_code=404)

    # 更新主檔屬性
    e.description, e.amount, e.currency, e.exchange_rate = exp.description, exp.amount, exp.currency, exp.exchange_rate
    e.consumption_date, e.consumption_time = exp.consumption_date, exp.consumption_time

    # 清除舊有關聯並寫入新關聯
    db.query(models.ExpensePayment).filter(models.ExpensePayment.expense_id == expense_id).delete()
    db.query(models.ExpenseSplit).filter(models.ExpenseSplit.expense_id == expense_id).delete()
    for p in exp.payments: db.add(models.ExpensePayment(expense_id=e.id, user_id=p.user_id, amount_paid=p.amount_paid))
    for s in exp.splits: db.add(models.ExpenseSplit(expense_id=e.id, debtor_id=s.user_id, amount_owed=s.amount_owed))

    db.commit()
    return {"status": "ok"}

@app.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    e = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if e: 
        db.delete(e)
        db.commit() # 關聯資料會因 Cascade 設定自動一併刪除
    return {"status": "ok"}

@app.get("/trips/{trip_id}/expenses")
def get_trip_expenses(trip_id: int, db: Session = Depends(get_db)):
    # 透過 ORM 進行資料篩選與排序
    expenses = db.query(models.Expense).filter(models.Expense.trip_id == trip_id).order_by(models.Expense.consumption_date.desc(), models.Expense.consumption_time.desc()).all()

    # 將查詢結果與關聯的付款/分攤明細包裝回傳給前端
    return [
        {
            "id": e.id,
            "description": e.description,
            "amount": e.amount,
            "currency": e.currency,
            "exchange_rate": e.exchange_rate,
            "consumption_date": e.consumption_date,
            "consumption_time": e.consumption_time,
            "payments": [{"user_id": p.user_id, "amount": p.amount_paid} for p in e.payments],
            "splits": [{"user_id": s.debtor_id, "amount": s.amount_owed} for s in e.splits]
        } for e in expenses
    ]

# --- 還款管理 ---
@app.post("/trips/{trip_id}/repayments")
def create_repayment(trip_id: int, rep: RepaymentCreate, db: Session = Depends(get_db)):
    new_rep = models.Repayment(trip_id=trip_id, sender_id=rep.sender_id, receiver_id=rep.receiver_id, amount=rep.amount)
    db.add(new_rep); db.commit()
    return {"status": "success"}

@app.get("/trips/{trip_id}/repayments")
def get_repayments(trip_id: int, db: Session = Depends(get_db)):
    return db.query(models.Repayment).filter(models.Repayment.trip_id == trip_id).order_by(models.Repayment.created_at.desc()).all()

@app.put("/repayments/{repayment_id}")
def update_repayment(repayment_id: int, rep: RepaymentCreate, db: Session = Depends(get_db)):
    r = db.query(models.Repayment).filter(models.Repayment.id == repayment_id).first()
    if r: 
        r.sender_id, r.receiver_id, r.amount = rep.sender_id, rep.receiver_id, rep.amount; db.commit()
    return {"status": "ok"}

@app.delete("/repayments/{repayment_id}")
def delete_repayment(repayment_id: int, db: Session = Depends(get_db)):
    r = db.query(models.Repayment).filter(models.Repayment.id == repayment_id).first()
    if r: 
        trip_id = r.trip_id
        db.delete(r); db.commit()
    return {"status": "ok"}

# --- 結算核心 ---
@app.get("/trips/{trip_id}/settlement")
def get_settlement(trip_id: int, db: Session = Depends(get_db)):
    users = db.query(models.User).filter(models.User.trip_id == trip_id).all()
    expenses = db.query(models.Expense).filter(models.Expense.trip_id == trip_id).all()
    repayments = db.query(models.Repayment).filter(models.Repayment.trip_id == trip_id).all()
    
    # 在摘要字典裡加上 "total_expense": 0.0 的初始值
    summary = {u.id: {"name": u.name, "initial": 0.0, "current": 0.0, "is_active": u.is_active, "total_expense": 0.0} for u in users}
    
    for e in expenses:
        for p in e.payments:
            if p.user_id in summary: summary[p.user_id]["initial"] += p.amount_paid * e.exchange_rate
        for s in e.splits:
            if s.debtor_id in summary:
                summary[s.debtor_id]["initial"] -= s.amount_owed * e.exchange_rate
                # 同時累加這筆花費到該成員的「個人總花費」中 (換算為台幣)
                summary[s.debtor_id]["total_expense"] += s.amount_owed * e.exchange_rate
                
    for uid in summary: summary[uid]["current"] = summary[uid]["initial"]
    
    for r in repayments:
        if r.sender_id in summary: summary[r.sender_id]["current"] += r.amount
        if r.receiver_id in summary: summary[r.receiver_id]["current"] -= r.amount
        
    initial_debt = sum(abs(v["initial"]) for v in summary.values() if v["initial"] < 0)
    current_debt = sum(abs(v["current"]) for v in summary.values() if v["current"] < 0)
    progress = ((initial_debt - current_debt) / initial_debt * 100) if initial_debt > 0 else 100.0
    
    # 把 total_expense 加進最終回傳的清單中
    balances = [{"name": data["name"], "balance": round(data["current"], 0), "status": "仍應收回" if data["current"] >= 0 else "仍應補繳", "total_expense": round(data["total_expense"], 0)} for uid, data in summary.items() if data["is_active"] or abs(data["current"]) > 1.0]
    return {"balances": balances, "progress": round(max(0, min(100, progress)), 1)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)