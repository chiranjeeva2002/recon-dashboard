from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.deps import get_optional_user
from app import models

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def root(user: models.User | None = Depends(get_optional_user)):
    return RedirectResponse(url="/dashboard" if user else "/login")


@router.get("/login")
def login_page(request: Request, user: models.User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/signup")
def signup_page(request: Request, user: models.User | None = Depends(get_optional_user)):
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("signup.html", {"request": request})


@router.get("/dashboard")
def dashboard_page(request: Request, user: models.User | None = Depends(get_optional_user)):
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard.html", {"request": request, "user_email": user.email})