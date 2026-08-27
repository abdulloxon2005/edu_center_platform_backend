from fastapi import APIRouter
from app.api.v1 import (
    auth, users, courses, groups, attendance,
    homework, finance, crm, gamification, payments, analytics,
    branches, certificates, support, audit, reports, telegram_api
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(courses.router, prefix="/courses", tags=["Courses & Rooms"])
api_router.include_router(groups.router, prefix="/groups", tags=["Groups"])
api_router.include_router(attendance.router, prefix="/attendance", tags=["Attendance"])
api_router.include_router(homework.router, prefix="/homework", tags=["Homework"])
api_router.include_router(finance.router, prefix="/finance", tags=["Finance & Dashboard"])
api_router.include_router(crm.router, prefix="/crm", tags=["CRM & Leads"])
api_router.include_router(gamification.router, prefix="/gamification", tags=["Gamification & Coin Shop"])
api_router.include_router(payments.router, prefix="/payments", tags=["Click/Payme Merchant Webhooks"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Exams, Analytics & Leaderboard"])
api_router.include_router(branches.router, prefix="/branches", tags=["Branches"])
api_router.include_router(certificates.router, prefix="/certificates", tags=["Certificates"])
api_router.include_router(support.router, prefix="/support", tags=["Support"])
api_router.include_router(audit.router, prefix="/audit", tags=["Audit"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports & Analytics"])
api_router.include_router(telegram_api.router, prefix="/telegram", tags=["Telegram Bot API"])
