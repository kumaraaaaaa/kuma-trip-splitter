from sqlalchemy import Column, Integer, String, Float, ForeignKey, Boolean, Table
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# 關聯表：處理 AppUser (帳號) 與 Trip (旅程) 的多對多關係
user_trip_association = Table('user_trips', Base.metadata,
    Column('app_user_id', Integer, ForeignKey('app_users.id')),
    Column('trip_id', Integer, ForeignKey('trips.id'))
)

# 系統登入帳戶
class AppUser(Base):
    __tablename__ = "app_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)  
    trips = relationship("Trip", secondary=user_trip_association, back_populates="app_users")

# 旅程本體
class Trip(Base):
    __tablename__ = "trips"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    invite_code = Column(String, unique=True, index=True) # 6碼邀請碼
    
    app_users = relationship("AppUser", secondary=user_trip_association, back_populates="trips")
    users = relationship("User", cascade="all, delete") 
    expenses = relationship("Expense", cascade="all, delete")
    repayments = relationship("Repayment", cascade="all, delete")

# 旅伴名單
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    is_active = Column(Boolean, default=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))

class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    amount = Column(Float)
    currency = Column(String)
    exchange_rate = Column(Float)
    description = Column(String)
    consumption_date = Column(String)
    consumption_time = Column(String)
    payments = relationship("ExpensePayment", cascade="all, delete")
    splits = relationship("ExpenseSplit", cascade="all, delete")

class ExpensePayment(Base):
    __tablename__ = "expense_payments"
    id = Column(Integer, primary_key=True, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    amount_paid = Column(Float)

class ExpenseSplit(Base):
    __tablename__ = "expense_splits"
    id = Column(Integer, primary_key=True, index=True)
    expense_id = Column(Integer, ForeignKey("expenses.id"))
    debtor_id = Column(Integer, ForeignKey("users.id"))
    amount_owed = Column(Float)

class Repayment(Base):
    __tablename__ = "repayments"
    id = Column(Integer, primary_key=True, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float)
    created_at = Column(String, default="now")