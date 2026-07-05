from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")

router = APIRouter(tags=["web"])


@router.get("/web", response_class=HTMLResponse)
def web_page(request: Request):
    return templates.TemplateResponse("web.html", {"request": request})


@router.get("/admin-web", response_class=HTMLResponse)
def admin_web_page(request: Request):
    return templates.TemplateResponse("admin_web.html", {"request": request})
