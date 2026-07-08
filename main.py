import uvicorn
import random
import csv
import io
from fastapi import FastAPI, Depends, HTTPException, Query, Form, Request, status, Body
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from datetime import date, datetime, timedelta
import calendar
import os
import hashlib
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
from typing import List, Optional

import models
import schemas

# Security Settings
SECRET_KEY = os.getenv("SECRET_KEY", "n-vision-dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SQLALCHEMY_DATABASE_URL = "sqlite:///./n-vision.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

models.Base.metadata.create_all(bind=engine)

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

app = FastAPI(title="N-VISION - Project & Employee Management System")

# Security Middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In Produktion einschränken!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP - Erweitert um CDN für Charts, Mermaid und SortableJS sowie Google Fonts zu erlauben
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:;"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

templates = Jinja2Templates(directory="templates")

# Cache busting for static files
def static_url(path: str):
    full_path = os.path.join("static", path.replace("/static/", "", 1).lstrip("/"))
    if os.path.exists(full_path):
        mtime = int(os.path.getmtime(full_path))
        return f"{path}?v={mtime}"
    return path

templates.env.globals["static_url"] = static_url

# --- Security Helpers ---
def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except (ValueError, Exception):
        # Legacy SHA256 fallback
        sha256_hash = hashlib.sha256(plain_password.encode()).hexdigest()
        return sha256_hash == hashed_password

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None
    user = db.query(models.User).filter(models.User.username == username).first()
    return user

def login_required(user: models.User = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def admin_required(user: models.User = Depends(login_required)):
    if user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# Context Processor for templates

@app.middleware("http")
async def add_global_data_to_request(request: Request, call_next):
    db = SessionLocal()
    request.state.user = await get_current_user(request, db)
    
    # Zentrales Planungsjahr laden
    # Planungjahr ist immer das aktuelle Jahr
    request.state.planning_year = date.today().year
    
    # Jahre berechnen: Vorjahr, Aktuelles Jahr und zwei Folgejahre
    real_today_year = date.today().year
    years = [real_today_year - 1, real_today_year, real_today_year + 1, real_today_year + 2]
    
    request.state.available_years = sorted(list(set(years)))
    
    # Kritische Projekte (Prio 1) für das Overlay laden
    critical_projects = []
    if request.state.user:
        critical_projects = db.query(models.Project).filter(
            models.Project.priority == 1,
            models.Project.status != models.ProjectStatus.COMPLETED
        ).order_by(models.Project.end_date.asc()).all()
    request.state.critical_projects = critical_projects
    
    db.close()
    response = await call_next(request)
    return response

# Template Global Variables
templates.env.globals["get_critical_projects"] = lambda request: request.state.critical_projects
templates.env.globals["planning_year"] = lambda request: request.state.planning_year
templates.env.globals["available_years"] = lambda request: request.state.available_years

# --- Auth Routes ---
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.post("/login")
def login(response: RedirectResponse, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        return RedirectResponse(url="/login?error=Invalid credentials", status_code=status.HTTP_303_SEE_OTHER)
    
    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=access_token, httponly=True, samesite="lax")
    return response

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    return response

# --- Helper for Progress ---
def calculate_project_progress(project: models.Project, db: Session):
    total_booked = db.query(func.sum(models.Booking.hours)).filter(models.Booking.project_id == project.id).scalar() or 0.0
    # Assuming 1 PT = 8 hours
    total_planned_hours = (project.pt_intern_planned + project.pt_extern_planned) * 8.0
    
    if total_planned_hours > 0:
        progress = (total_booked / total_planned_hours) * 100
        return round(progress, 1)
    
    # Bugfix: Wenn Stunden gebucht wurden, aber kein Plan existiert,
    # zeigen wir 100% an (da der Plan 0 ist, ist jede Stunde "über Plan").
    if total_booked > 0:
        return 100.0
        
    return 0.0

# --- UI Routes ---

@app.get("/", response_class=HTMLResponse)
def ui_heatmap(request: Request, year: Optional[int] = None, team_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not request.state.user:
        return RedirectResponse(url="/login")
    
    if year is None: 
        real_today_year = date.today().year
        if real_today_year in request.state.available_years:
            year = real_today_year
        else:
            year = request.state.planning_year
    
    heatmap_data = get_annual_heatmap(year, db, team_id=team_id)
    teams = db.query(models.Team).all()
    
    return templates.TemplateResponse(
        request=request, name="heatmap.html", context={
            "heatmap": heatmap_data, 
            "year": year,
            "teams": teams,
            "selected_team_id": team_id,
            "active_page": "heatmap",
            "user": request.state.user
        }
    )

@app.get("/api/heatmap/detail/{employee_id}/{year}/{month}", response_model=schemas.CapacityDetail)
def get_capacity_detail(employee_id: int, year: int, month: int, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    
    total_cap = employee.weekly_hours / 40.0
    service_allocs = db.query(models.ServiceAllocation).filter(models.ServiceAllocation.employee_id == employee.id).all()
    service_cap = sum(s.capacity_percent for s in service_allocs) / 100.0
    
    staffings = db.query(models.Staffing).filter(
        models.Staffing.employee_id == employee.id,
        models.Staffing.start_date <= last_day,
        models.Staffing.end_date >= first_day
    ).all()
    
    staffing_details = []
    staffed_cap = 0.0
    for s in staffings:
        # Get bookings for this project and employee in this month
        booked = db.query(func.sum(models.Booking.hours)).filter(
            models.Booking.employee_id == employee.id,
            models.Booking.project_id == s.project_id,
            models.Booking.date >= first_day,
            models.Booking.date <= last_day
        ).scalar() or 0.0
        
        staffing_details.append(schemas.StaffingDetail(
            project_name=s.project.name,
            capacity_fte=s.capacity_fte,
            booked_hours=booked
        ))
        staffed_cap += s.capacity_fte
        
    return schemas.CapacityDetail(
        employee_name=employee.name,
        year=year,
        month=month,
        total_capacity_fte=total_cap,
        service_capacity_fte=service_cap,
        staffings=staffing_details,
        free_capacity_fte=total_cap - service_cap - staffed_cap
    )

def get_annual_heatmap(year: int, db: Session, team_id: Optional[int] = None):
    query = db.query(models.Employee)
    if team_id:
        query = query.filter(models.Employee.team_id == team_id)
    employees = query.all()
    results = []
    
    for emp in employees:
        total_cap = emp.weekly_hours / 40.0
        service_allocs = db.query(models.ServiceAllocation).filter(models.ServiceAllocation.employee_id == emp.id).all()
        service_cap = sum(s.capacity_percent for s in service_allocs) / 100.0
        
        months_data = []
        for m in range(1, 13):
            first_day = date(year, m, 1)
            last_day = date(year, m, calendar.monthrange(year, m)[1])
            
            staffed_cap = get_employee_staffed_capacity(db, emp.id, first_day, last_day)
            free_cap = total_cap - service_cap - staffed_cap
            
            status = "ok"
            if free_cap < -0.01: # Kleine Toleranz für Floating Point
                status = "error"
            elif free_cap < 0.1:
                status = "warning"
                
            months_data.append(schemas.MonthlyCapacity(
                month=m,
                staffed_capacity_fte=staffed_cap,
                service_capacity_fte=service_cap,
                free_capacity_fte=free_cap,
                status=status
            ))
            
        results.append(schemas.AnnualHeatmapEntry(
            employee_id=emp.id,
            employee_name=emp.name,
            year=year,
            total_capacity_fte=total_cap,
            months=months_data
        ))
    return results

def get_employee_staffed_capacity(db: Session, employee_id: int, start_date: date, end_date: date) -> float:
    staffings = db.query(models.Staffing).filter(
        models.Staffing.employee_id == employee_id,
        models.Staffing.start_date <= end_date,
        models.Staffing.end_date >= start_date
    ).all()
    
    return sum(s.capacity_fte for s in staffings)

@app.get("/ui/projects", response_class=HTMLResponse)
def ui_projects(request: Request, division: Optional[str] = None, show_completed: bool = Query(False), db: Session = Depends(get_db)):
    if not request.state.user:
        return RedirectResponse(url="/login")
    
    if request.state.user.role == models.UserRole.ADMIN:
        query = db.query(models.Project)
    else:
        # Employees only see projects they are staffed on
        query = db.query(models.Project).join(models.Staffing).filter(models.Staffing.employee_id == request.state.user.employee_id)
    
    if division:
        query = query.filter(models.Project.division == division)
        
    if not show_completed:
        query = query.filter(models.Project.status != models.ProjectStatus.COMPLETED)
        
    projects = query.all()
    
    # Add progress to each project object (dynamically)
    for p in projects:
        p.progress = calculate_project_progress(p, db)

    return templates.TemplateResponse(
        request=request, name="projects.html", context={
            "projects": projects,
            "active_page": "projects",
            "user": request.state.user,
            "selected_division": division,
            "show_completed": show_completed
        }
    )

@app.get("/ui/bookings", response_class=HTMLResponse)
def ui_bookings(request: Request, project_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    if not request.state.user or request.state.user.role != models.UserRole.EMPLOYEE:
        return RedirectResponse(url="/")
    
    assigned_projects = db.query(models.Project).join(models.Staffing).filter(
        models.Staffing.employee_id == request.state.user.employee_id,
        models.Project.status != models.ProjectStatus.COMPLETED
    ).all()
    bookings = db.query(models.Booking).filter(models.Booking.employee_id == request.state.user.employee_id).order_by(models.Booking.date.desc()).all()
    
    return templates.TemplateResponse(
        request=request, name="bookings.html", context={
            "assigned_projects": assigned_projects,
            "bookings": bookings,
            "today": date.today().isoformat(),
            "active_page": "bookings",
            "user": request.state.user,
            "selected_project_id": project_id
        }
    )

@app.post("/ui/bookings/add")
def ui_add_booking(
    project_id: int = Form(...),
    date: date = Form(...),
    hours: float = Form(...),
    description: Optional[str] = Form(None),
    request: Request = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(login_required)
):
    if user.role != models.UserRole.EMPLOYEE:
        raise HTTPException(status_code=403, detail="Only employees can book hours")
    
    # Check if employee is staffed on this project
    staffing = db.query(models.Staffing).filter(
        models.Staffing.project_id == project_id,
        models.Staffing.employee_id == user.employee_id
    ).first()
    
    if not staffing and user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="You can only book hours on projects you are staffed on")
    
    db_booking = models.Booking(
        employee_id=user.employee_id,
        project_id=project_id,
        date=date,
        hours=hours,
        description=description
    )
    db.add(db_booking)
    db.commit()
    return RedirectResponse(url="/ui/bookings", status_code=303)

@app.get("/ui/projects/add", response_class=HTMLResponse)
def ui_add_project_form(request: Request, user: models.User = Depends(admin_required)):
    return templates.TemplateResponse(
        request=request, name="project_add.html", context={
            "active_page": "project_add"
        }
    )

@app.post("/ui/projects/add")
def ui_add_project(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    business_value: Optional[str] = Form(None),
    internal_number: Optional[str] = Form(None),
    division: Optional[str] = Form(None),
    start_date: date = Form(...),
    end_date: date = Form(...),
    status: models.ProjectStatus = Form(...),
    priority: int = Form(1),
    responsible_it: Optional[str] = Form(None),
    responsible_fb: Optional[str] = Form(None),
    pab_approval: bool = Form(False),
    cats_number: Optional[str] = Form(None),
    pt_intern_pab: float = Form(0.0),
    pt_intern_planned: float = Form(0.0),
    pt_extern_planned: float = Form(0.0),
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    db_project = models.Project(
        name=name,
        description=description,
        business_value=business_value,
        internal_number=internal_number,
        division=division,
        start_date=start_date,
        end_date=end_date,
        status=status,
        priority=priority,
        responsible_it=responsible_it,
        responsible_fb=responsible_fb,
        pab_approval=1 if pab_approval else 0,
        cats_number=cats_number,
        pt_intern_pab=pt_intern_pab,
        pt_intern_planned=pt_intern_planned,
        pt_extern_planned=pt_extern_planned
    )
    db.add(db_project)
    db.commit()
    return RedirectResponse(url="/ui/projects", status_code=303)

@app.get("/ui/projects/{project_id}/edit", response_class=HTMLResponse)
def ui_edit_project_form(request: Request, project_id: int, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return templates.TemplateResponse(
        request=request, name="project_edit.html", context={
            "project": project,
            "active_page": "projects"
        }
    )

@app.post("/ui/projects/{project_id}/edit")
def ui_edit_project(
    project_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    business_value: Optional[str] = Form(None),
    internal_number: Optional[str] = Form(None),
    division: Optional[str] = Form(None),
    start_date: date = Form(...),
    end_date: date = Form(...),
    status: models.ProjectStatus = Form(...),
    priority: int = Form(1),
    responsible_it: Optional[str] = Form(None),
    responsible_fb: Optional[str] = Form(None),
    pab_approval: bool = Form(False),
    cats_number: Optional[str] = Form(None),
    pt_intern_pab: float = Form(0.0),
    pt_intern_planned: float = Form(0.0),
    pt_extern_planned: float = Form(0.0),
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.name = name
    project.description = description
    project.business_value = business_value
    project.internal_number = internal_number
    project.division = division
    project.start_date = start_date
    project.end_date = end_date
    project.status = status
    project.priority = priority
    project.responsible_it = responsible_it
    project.responsible_fb = responsible_fb
    project.pab_approval = 1 if pab_approval else 0
    project.cats_number = cats_number
    project.pt_intern_pab = pt_intern_pab
    project.pt_intern_planned = pt_intern_planned
    project.pt_extern_planned = pt_extern_planned
    
    db.commit()
    return RedirectResponse(url="/ui/projects", status_code=303)

@app.post("/ui/projects/{project_id}/status")
def ui_update_project_status(project_id: int, status: models.ProjectStatus = Form(...), db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.status = status
    db.commit()
    return RedirectResponse(url="/ui/projects", status_code=303)

@app.post("/ui/projects/{project_id}/complete")
def ui_complete_project(project_id: int, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.status = models.ProjectStatus.COMPLETED
    db.commit()
    return RedirectResponse(url="/ui/projects", status_code=303)

@app.post("/ui/projects/reorder")
async def ui_reorder_projects(project_ids: list[int] = Body(...), db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    """Aktualisiert die Priorität (Reihenfolge) mehrerer Projekte gleichzeitig."""
    for index, p_id in enumerate(project_ids):
        project = db.query(models.Project).filter(models.Project.id == p_id).first()
        if project:
            project.priority = index + 1
    db.commit()
    return {"status": "ok"}

@app.get("/ui/projects/{project_id}", response_class=HTMLResponse)
def ui_project_detail(request: Request, project_id: int, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    progress = calculate_project_progress(project, db)
    # Ensure progress is a float
    progress = float(progress)
    
    return templates.TemplateResponse(
        request=request, name="project_detail.html", context={
            "project": project,
            "progress": progress,
            "active_page": "projects"
        }
    )

@app.post("/ui/projects/{project_id}/milestones/add")
def ui_add_milestone(
    project_id: int,
    name: str = Form(...),
    date: date = Form(...),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    db_milestone = models.Milestone(
        project_id=project_id,
        name=name,
        date=date,
        description=description
    )
    db.add(db_milestone)
    db.commit()
    return RedirectResponse(url=f"/ui/projects/{project_id}", status_code=303)

@app.post("/ui/projects/{project_id}/milestones/{milestone_id}/delete")
def ui_delete_milestone(project_id: int, milestone_id: int, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    milestone = db.query(models.Milestone).filter(models.Milestone.id == milestone_id).first()
    if milestone:
        db.delete(milestone)
        db.commit()
    return RedirectResponse(url=f"/ui/projects/{project_id}", status_code=303)

@app.get("/ui/employees", response_class=HTMLResponse)
def ui_employees(request: Request, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    employees = db.query(models.Employee).all()
    teams = db.query(models.Team).all()
    return templates.TemplateResponse(
        request=request, name="employees.html", context={
            "employees": employees,
            "teams": teams,
            "active_page": "employees",
            "user": user
        }
    )

@app.post("/ui/employees/add")
def ui_add_employee(
    name: str = Form(...),
    type: models.ResourceType = Form(...),
    weekly_hours: float = Form(40.0),
    team_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    db_emp = models.Employee(name=name, type=type, weekly_hours=weekly_hours, team_id=team_id, employment_start=date.today())
    db.add(db_emp)
    db.commit()
    return RedirectResponse(url="/ui/employees", status_code=303)

@app.get("/ui/employees/{employee_id}/plan", response_class=HTMLResponse)
def ui_employee_plan(request: Request, employee_id: int, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return templates.TemplateResponse(
        request=request, name="employee_plan.html", context={
            "employee": employee,
            "active_page": "employees"
        }
    )

@app.post("/ui/employees/{employee_id}/plan")
def ui_update_employee_plan(
    employee_id: int,
    annual_hours_target: float = Form(...),
    service_capacity_percent: float = Form(0.0),
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    employee.annual_hours_target = annual_hours_target
    
    # Update or create service allocation
    service_alloc = db.query(models.ServiceAllocation).filter(models.ServiceAllocation.employee_id == employee_id).first()
    if service_alloc:
        service_alloc.capacity_percent = service_capacity_percent
    else:
        new_alloc = models.ServiceAllocation(
            employee_id=employee_id,
            capacity_percent=service_capacity_percent,
            description="Allgemeine Linienaufgaben"
        )
        db.add(new_alloc)
        
    db.commit()
    return RedirectResponse(url="/ui/employees", status_code=303)

@app.get("/ui/staffing/add", response_class=HTMLResponse)
def ui_staffing_add_form(request: Request, project_id: int, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    employees = db.query(models.Employee).all()
    teams = db.query(models.Team).all()
    roles = db.query(models.Role).all()
    
    # Auslastung für jeden Mitarbeiter im Projektzeitraum berechnen
    employee_data = []
    for emp in employees:
        total_cap = emp.weekly_hours / 40.0
        service_allocs = db.query(models.ServiceAllocation).filter(models.ServiceAllocation.employee_id == emp.id).all()
        service_cap = sum(s.capacity_percent for s in service_allocs) / 100.0
        
        # Bestehende Staffings im Projektzeitraum (ohne das aktuelle Projekt, falls schon was da ist)
        current_staffed = get_employee_staffed_capacity(db, emp.id, project.start_date, project.end_date)
        
        # Wir wollen wissen, wie viel Kapazität noch frei ist
        free_cap = total_cap - service_cap - current_staffed
        
        employee_data.append({
            "emp": emp,
            "total_cap": total_cap,
            "service_cap": service_cap,
            "current_staffed": current_staffed,
            "free_cap": free_cap,
            "utilization_percent": round((service_cap + current_staffed) / total_cap * 100) if total_cap > 0 else 0
        })

    return templates.TemplateResponse(
        request=request, name="staffing_add.html", context={
            "project": project,
            "employee_data": employee_data,
            "teams": teams,
            "roles": roles
        }
    )

@app.post("/ui/staffing/add")
def ui_add_staffing(
    project_id: int = Form(...),
    employee_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    capacity_fte: float = Form(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    db_staffing = models.Staffing(
        project_id=project_id, 
        employee_id=employee_id, 
        start_date=start_date, 
        end_date=end_date, 
        capacity_fte=capacity_fte
    )
    db.add(db_staffing)
    db.commit()
    return RedirectResponse(url="/ui/projects", status_code=303)

@app.post("/ui/staffing/bulk_add")
async def ui_bulk_add_staffing(
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(admin_required)
):
    form_data = await request.form()
    project_id = int(form_data.get("project_id"))
    
    # Die Form-Daten kommen als Mehrfachwerte
    # employee_ids ist eine Liste der ausgewählten IDs
    employee_ids = form_data.getlist("selected_employees")
    
    for emp_id in employee_ids:
        emp_id = int(emp_id)
        start_date_str = form_data.get(f"start_date_{emp_id}")
        end_date_str = form_data.get(f"end_date_{emp_id}")
        capacity_fte_str = form_data.get(f"capacity_fte_{emp_id}")
        
        if start_date_str and end_date_str and capacity_fte_str:
            db_staffing = models.Staffing(
                project_id=project_id,
                employee_id=emp_id,
                start_date=date.fromisoformat(start_date_str),
                end_date=date.fromisoformat(end_date_str),
                capacity_fte=float(capacity_fte_str)
            )
            db.add(db_staffing)
    
    db.commit()
    return RedirectResponse(url="/ui/projects", status_code=303)

# API Endpoints
@app.get("/teams/", response_model=List[schemas.Team])
def get_teams(db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    return db.query(models.Team).all()

@app.post("/teams/", response_model=schemas.Team)
def create_team(team: schemas.TeamCreate, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    db_team = models.Team(name=team.name)
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return db_team

@app.get("/roles/", response_model=List[schemas.Role])
def get_roles(db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    return db.query(models.Role).all()

@app.post("/roles/", response_model=schemas.Role)
def create_role(role: schemas.RoleCreate, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    db_role = models.Role(name=role.name)
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

@app.get("/employees/", response_model=List[schemas.Employee])
def get_employees(db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    return db.query(models.Employee).all()

@app.post("/employees/", response_model=schemas.Employee)
def create_employee(employee: schemas.EmployeeCreate, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    db_employee = models.Employee(**employee.model_dump())
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee

@app.get("/projects/", response_model=List[schemas.Project])
def get_projects(db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    return db.query(models.Project).all()

@app.post("/projects/", response_model=schemas.Project)
def create_project(project: schemas.ProjectCreate, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    db_project = models.Project(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project

@app.get("/staffings/", response_model=List[schemas.Staffing])
def get_staffings(project_id: Optional[int] = None, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    query = db.query(models.Staffing)
    if project_id:
        query = query.filter(models.Staffing.project_id == project_id)
    return query.all()


# @app.post("/seed/")
# def seed_database(db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
#     # 1. Clear existing data
#     db.query(models.Milestone).delete()
#     db.query(models.Booking).delete()
#     db.query(models.Staffing).delete()
#     db.query(models.ServiceAllocation).delete()
#     db.query(models.Setting).delete()
#     db.query(models.Project).delete()
#     db.query(models.Employee).delete()
#     db.query(models.Role).delete()
#     db.query(models.Team).delete()
#     db.commit()
#     
#     # 2. Create Teams
#     teams = [models.Team(name=n) for n in ["Netzbetrieb", "Energiewirtschaft", "IT-Infrastruktur", "Kundenservice"]]
#     db.add_all(teams)
#     db.commit()
#     for t in teams: db.refresh(t)
#     
#     # 3. Create Roles
#     roles = [models.Role(name=n) for n in ["Projektleiter", "Fachexperte", "Systemarchitekt", "Analyst"]]
#     db.add_all(roles)
#     db.commit()
#     for r in roles: db.refresh(r)
#     
#     # 4. Create Resources
#     names = [
#         "Lukas Leuchtkraft", "Marina Megawatt", "Klaus Kilowatt", "Sven Spannung", "Petra Photovoltaik",
#         "Viktor Volt", "Anja Ampere", "Olaf Ohm", "Wanda Watt", "Hannes Hertz",
#         "Berta Biogas", "Windfried Windkraft", "Sonja Solar", "Gerald Generator", "Theresa Thermik",
#         "Ursula Umspannwerk", "Niklas Netz", "Isabel Isoliert", "Konrad Kabel", "Lara Ladestrom",
#         "Marco Messwesen", "Nadine Niederspannung", "Oliver Oberleitung", "Paula Peak", "Quentin Quartierspeicher",
#         "Rainer Regelenergie", "Sabine Smartmeter", "Thomas Transformator", "Ulrich Übertragung", "Vera Verbraucher",
#         "Walter Wasserkraft", "Xenia Xenonlicht", "Yvonne Y-Kabel", "Zeno Zelltechnologie", "Armin Ableser",
#         "Beate Brennstoffzelle", "Christian Cogeneration", "Doris Dampfturbine", "Erik Einspeisung", "Friederike Fernwärme",
#         "Gisela Geothermie", "Holger Hochspannung", "Ines Infrarot", "Jochen Joule", "Katrin Kohlenstoff",
#         "Lothar Lithium", "Monika Mittelspannung", "Norbert Netzfrequenz", "Ortwin Ökostrom", "Pia Pumpspeicher",
#         "Rüdiger Reaktor", "Saskia Sektorenkopplung", "Tanja Tarif", "Uwe Unterbrechungsfrei", "Volker Versorgungsicherheit",
#         "Winfried Wirkleistung", "Xaver X-Achse", "Yannick Youngtimer-Kraftwerk", "Zita Zentralsteuerung", "Albert Abrechnung",
#         "Barbara Batteriestand", "Claus Cloud-Energie", "Dieter Drehstrom", "Elke Energieeffizienz", "Frank Freileitung",
#         "Gabi Gastherme", "Helmut Heizwert", "Iris Intraday", "Jörg Jahresverbrauch", "Karin Kernkraft",
#         "Ludwig Lastgang", "Maren Marktdesign", "Niels Niedertarif", "Olga Off-Grid", "Paul Power-to-Gas",
#         "Regina Regelzone", "Stefan Strommix", "Tristan Trasse", "Ute Umweltschutz", "Valentin Verteilnetz",
#         "Werner Wechselstrom", "Yoke Yellow-Phase", "Zoe Zählerkasten", "Anton Anlagenbau", "Bastian Bereitschaft",
#         "Carsten CO2-Zertifikat", "Daniela Direktvermarktung", "Egon Erdgas", "Falk Fernauslesung", "Gudrun Grundversorger"
#     ]
#     
#     # Ergänze falls nötig auf 100
#     while len(names) < 100:
#         names.append(f"Energiemitarbeiter {len(names) + 1}")
#
#     all_employees = []
#     for i, name in enumerate(names):
#         emp_type = models.ResourceType.INTERNAL if i % 5 != 0 else models.ResourceType.EXTERNAL
#         emp = models.Employee(
#             name=name,
#             type=emp_type,
#             role_id=roles[i % len(roles)].id,
#             team_id=teams[i % len(teams)].id,
#             weekly_hours=40 if emp_type == models.ResourceType.INTERNAL else 20,
#             employment_start=date(2023, 1, 1) + timedelta(days=i*10)
#         )
#         all_employees.append(emp)
#     
#     db.add_all(all_employees)
#     db.commit()
#     for emp in all_employees: db.refresh(emp)
#     
#     res1, res2, res3 = all_employees[0], all_employees[1], all_employees[2]
#     
#     # 5. Create Projects from raw data
#     random.seed(42)  # For reproducible mixing
#     raw_csv_data = """project_code;name;description;bereich;typ;status;priority;start_date;end_date;responsible_it;responsible_business;pab_approved;cats_order;planned_internal_pt;planned_external_pt;actual_pt;source_hint
# E-001;Projekt 'Phönix' Netzleitstelle;Modernisierung der zentralen Steuerungseinheit;Netz;;Ja;1;;;;;;27030137;150;50;;Fiktiv
# E-002;Operation 'Grüner Wasserstoff';Aufbau einer Elektrolyse-Teststrecke;Erzeugung;;Ja;1;;;;;;27028577;200;100;;Fiktiv
# E-003;Initiative 'Sonnenwende';Flächendeckender Ausbau von PV-Dachsystemen;Innovation;;Nein;2;;;;;;27030336;300;200;;Fiktiv
# E-004;Mission 'Nordsee-Wind';Anbindung neuer Offshore-Kapazitäten;Erzeugung;;Ja;1;;;;;;27028579;80;10;;Fiktiv
# E-005;Projekt 'E-Highway';Aufbau von HPC-Ladeparks an Autobahnen;Vertrieb;;Ja;2;;;;;;27030335;120;40;;Fiktiv
# E-006;Programm 'Digitaler Zähler';Beschleunigter Rollout von Smart-Gateways;Messwesen;;Ja;1;;;;;;51127661;500;0;;Fiktiv
# E-007;Vorhaben 'Biomethan-Boost';Einspeiseoptimierung für landwirtschaftliche Anlagen;Netz;;Ja;3;;;;;;51127662;90;20;;Fiktiv
# E-008;System 'Grid-Guardian';KI-gestützte Fehlererkennung im Verteilnetz;Netz;;Ja;1;;;;;;51127668;110;30;;Fiktiv
# E-009;Quartier 'Energie-Autark';Pilotprojekt für lokale Speicherlösungen;Netz;;Nein;2;;;;;;27030396;70;5;;Fiktiv
# E-010;Konzept 'Virtueller Trafo';Digitaler Zwilling für vorausschauende Wartung;Netz;;Ja;2;;;;;;27028583;180;60;;Fiktiv
# E-011;Offensive 'Küstenwind';Erweiterung der Windparks im Wattenmeer;Erzeugung;;Ja;1;;;;;;27029559;400;500;;Fiktiv
# E-012;Plattform 'Power-Trade';Neuentwicklung des Intraday-Handelsportals;Handel;;Ja;2;;;;;;0;130;20;;Fiktiv
# E-013;Kampagne 'Wärme-Zukunft';Umstellung von Gasheizungen auf Wärmepumpen;Vertrieb;;Ja;2;;;;;;27030245;100;10;;Fiktiv
# E-014;Asset-Management 'Infrastruktur 4.0';Automatisierung der Netzbetriebsmittel-Inventur;IT;;Ja;3;;;;;;27030337;140;40;;Fiktiv
# E-015;Projekt 'Deep-Learning-Load';Neuronale Netze für die Lastprognose;IT;;Ja;1;;;;;;27030542;160;30;;Fiktiv
# E-016;Geothermie-Sondierung 'Hot-Rock';Tiefenbohrung für geothermische Fernwärme;Erzeugung;;Nein;3;;;;;;27030556;250;150;;Fiktiv
# E-017;LoRaWAN 'Smart-City-Netz';Aufbau eines Sensornetzwerks für Kommunen;IT;;Ja;3;;;;;;51142992;60;10;;Fiktiv
# E-018;Blockchain 'P2P-Energy';Dezentraler Handel zwischen Prosumern;Innovation;;Nein;4;;;;;;51155946;90;10;;Fiktiv
# E-019;Trasse 'Süd-Link-Connect';Integration neuer HGÜ-Leitungen;Netz;;Ja;1;;;;;;27030399;600;800;;Fiktiv
# E-020;Dashboard 'Eco-Transparency';Echtzeit-Anzeige des regionalen Strommix;Öffentlichkeit;;Ja;2;;;;;;0;40;5;;Fiktiv"""
#
#     # 5. Create Projects from raw data
#     random.seed(42)  # For reproducible mixing
#     reader = csv.DictReader(io.StringIO(raw_csv_data), delimiter=';')
#     all_imported_projects = []
#     
#     divisions = ["IT", "Netzgesellschaft", "Vertrieb", "Kraftwerk"]
#     
#     # Mitarbeiter-Namen für Zuweisung zu verantwortlichen Rollen
#     employee_names = [emp.name for emp in all_employees]
#     
#     for i, row in enumerate(reader):
#         # Mapping rules
#         name = row['name']
#         internal_number = row['project_code']
#         
#         # Durchmischte Zuweisung der Bereiche (reproduzierbar durch seed)
#         division = random.choice(divisions)
#         
#         # Status mapping
#         status_raw = row['pab_approved'].lower()
#         if "ja" in status_raw:
#             status = models.ProjectStatus.ACTIVE
#         elif "abgeschlossen" in status_raw:
#             status = models.ProjectStatus.COMPLETED
#         elif "zurückgestellt" in status_raw:
#             status = models.ProjectStatus.ON_HOLD
#         else:
#             status = models.ProjectStatus.PLANNING
#             
#         # Priority mapping (P1-P4)
#         priority_raw = row.get('priority', '')
#         if priority_raw and priority_raw.isdigit():
#             priority = int(priority_raw)
#         else:
#             # Zufällige Priorität 1-4 (reproduzierbar durch seed)
#             priority = random.randint(1, 4)
#
#         # Planned hours mapping
#         try:
#             pt_intern_raw = row.get('planned_internal_pt', '')
#             pt_extern_raw = row.get('planned_external_pt', '')
#             
#             # Falls Feld leer, weisen wir einen Standardwert zu, damit Fortschritt berechenbar ist
#             pt_intern = float(pt_intern_raw) if pt_intern_raw and pt_intern_raw.strip() else 10.0
#             pt_extern = float(pt_extern_raw) if pt_extern_raw and pt_extern_raw.strip() else 0.0
#         except ValueError:
#             pt_intern = 10.0
#             pt_extern = 0.0
#
#         p = models.Project(
#             name=name,
#             description=f"Automatischer Import für Projekt {name}.",
#             business_value="Hoher strategischer Wert für die Digitalisierungsstrategie.",
#             internal_number=internal_number,
#             division=division,
#             status=status,
#             priority=priority,
#             start_date=date(2026, 1, 1),
#             end_date=date(2026, 12, 31),
#             responsible_it=random.choice(employee_names) if row['responsible_it'] else None,
#             responsible_fb=random.choice(employee_names) if row['responsible_business'] else None,
#             cats_number=row['cats_order'],
#             pab_approval=1 if "ja" in status_raw else 0,
#             pt_intern_planned=pt_intern,
#             pt_extern_planned=pt_extern
#         )
#         all_imported_projects.append(p)
#     
#     db.add_all(all_imported_projects)
#     db.commit()
#     for p in all_imported_projects: db.refresh(p)
#
#     # Meilensteine für alle Projekte
#     for i, p in enumerate(all_imported_projects):
#         # Variierende Daten für Meilensteine
#         m1 = models.Milestone(project_id=p.id, name="Projekt-Kickoff", date=p.start_date + timedelta(days=14), description="Initiales Meeting")
#         m2 = models.Milestone(project_id=p.id, name="Konzept-Phase", date=p.start_date + timedelta(days=90), description="Abnahme Konzept")
#         m3 = models.Milestone(project_id=p.id, name="Go-Live", date=p.end_date - timedelta(days=60), description="Produktivsetzung")
#         db.add_all([m1, m2, m3])
#         
#         # Optional: Für jedes 3. Projekt einen zusätzlichen Meilenstein
#         if i % 3 == 0:
#             m4 = models.Milestone(project_id=p.id, name="Zwischenbericht", date=p.start_date + timedelta(days=180), description="Status-Update")
#             db.add(m4)
#     db.commit()
#     
#     # Referenzprojekte für Staffing
#     p1 = all_imported_projects[0]
#     p2 = all_imported_projects[2]
#     
#     # 6. Create Staffing
#     # Wir weisen Mitarbeitern Projekte zu, achten aber darauf, dass sie nicht überplant sind.
#     staffings = []
#     
#     # Wir verfolgen die Auslastung pro Mitarbeiter, um Überplanung zu vermeiden
#     employee_workload = {emp.id: 0.0 for emp in all_employees}
#     
#     # 7. Service Allocation (Linienaufgaben) zuerst, da diese die Grundlast bilden
#     # Alle Mitarbeiter haben etwas Grundlast in der Linie (10-20%)
#     for emp in all_employees:
#         base_load = float(random.choice([10, 15, 20]))
#         db.add(models.ServiceAllocation(
#             employee_id=emp.id, 
#             capacity_percent=base_load, 
#             description="Linienaufgaben / Grundlast"
#         ))
#         employee_workload[emp.id] += base_load / 100.0
#     
#     # Bestimme einige Projekte, die etwas mehr Aufmerksamkeit bekommen
#     important_projects = all_imported_projects[:15]
#     
#     for i, emp in enumerate(all_employees):
#         # Jedem Mitarbeiter 1-2 Projekte zuweisen (vorher 1-3)
#         # Seltener 2 Projekte, meistens 1
#         num_projects = 1 if random.random() > 0.2 else 2
#         
#         # Verfügbare Kapazität
#         # Wir lassen öfter eine leichte Überplanung zu oder gehen näher an die 100%
#         # Wahrscheinlichkeit für Überplanung leicht erhöhen (15%)
#         rand_val = random.random()
#         if rand_val > 0.85:
#              max_target = 1.2 # Rot
#         elif rand_val > 0.5:
#              max_target = 1.0 # Gelb/Orange
#         else:
#              max_target = 0.8 # Grün
#              
#         selected_projects = random.sample(all_imported_projects, num_projects)
#         
#         for proj in selected_projects:
#             remaining_cap = max_target - employee_workload[emp.id]
#             if remaining_cap <= 0.05:
#                 break
#                 
#             # Kapazität zwischen 0.1 und der verbleibenden Kapazität
#             # Wir geben etwas großzügigere Anteile
#             cap = round(random.uniform(0.1, max(0.2, remaining_cap)), 1)
#             
#             if cap > 0:
#                 s = models.Staffing(
#                     project_id=proj.id,
#                     employee_id=emp.id,
#                     start_date=date(2026, 1, 1),
#                     end_date=date(2026, 12, 31),
#                     capacity_fte=cap
#                 )
#                 staffings.append(s)
#                 employee_workload[emp.id] += cap
#                 
#     db.add_all(staffings)
#     
#     # 8. Buchungen (Ist-Stunden) erzeugen
#     # Um Fortschritt in Projekten zu zeigen, brauchen wir Buchungen.
#     # Wir buchen für das erste Halbjahr 2026.
#     # Achte darauf, dass der Fortschritt zwischen 0 und 100 liegt.
#     bookings = []
#     end_booking_date = date(2026, 7, 1)
#     
#     # Wir tracken die bereits gebuchten Stunden pro Projekt im Seed
#     project_booked_hours_seed = {}
#
#     for s in staffings[:150]: # Erste 150 Staffings bekommen Buchungen
#         # Projekt direkt aus der Liste der importierten Projekte holen für Effizienz
#         proj = next((p for p in all_imported_projects if p.id == s.project_id), None)
#         if not proj:
#             continue
#             
#         total_planned_hours = (proj.pt_intern_planned + proj.pt_extern_planned) * 8.0
#         if total_planned_hours <= 0:
#             continue
#
#         if proj.id not in project_booked_hours_seed:
#             # Zufälliger Zielfortschritt für dieses Projekt (zwischen 10% und 90%)
#             project_booked_hours_seed[proj.id] = {
#                 "current": 0.0,
#                 "target": total_planned_hours * random.uniform(0.1, 0.9)
#             }
#         
#         # Buche jede Woche etwas auf dieses Projekt
#         for week in range(20):
#             booking_date = s.start_date + timedelta(weeks=week, days=random.randint(0, 4))
#             if booking_date < end_booking_date:
#                 # Verbleibende Stunden für dieses Projekt
#                 remaining = project_booked_hours_seed[proj.id]["target"] - project_booked_hours_seed[proj.id]["current"]
#                 if remaining <= 0:
#                     break
#                 
#                 # Stunden basierend auf FTE, aber gedeckelt durch das Ziel
#                 hours_suggestion = s.capacity_fte * 40 * random.uniform(0.5, 1.0)
#                 hours = min(hours_suggestion, remaining)
#                 
#                 if hours > 0.1:
#                     b = models.Booking(
#                         employee_id=s.employee_id,
#                         project_id=s.project_id,
#                         date=booking_date,
#                         hours=round(hours, 1),
#                         description="Projektarbeit gemäß Staffing"
#                     )
#                     bookings.append(b)
#                     project_booked_hours_seed[proj.id]["current"] += round(hours, 1)
#     
#     db.add_all(bookings)
#     db.commit()

    # User-Seeding
    # Admin User
    admin_user = db.query(models.User).filter(models.User.username == "admin").first()
    if not admin_user:
        admin_user = models.User(
            username="admin",
            hashed_password=get_password_hash("admin"),
            role=models.UserRole.ADMIN
        )
        db.add(admin_user)

    # Employee User for Alice
    alice_user = db.query(models.User).filter(models.User.username == "alice").first()
    if not alice_user:
        alice_user = models.User(
            username="alice",
            hashed_password=get_password_hash("alice"),
            role=models.UserRole.EMPLOYEE,
            employee_id=res1.id
        )
        db.add(alice_user)

    db.commit()

    # Wenn der Request von einem Browser kommt (Redirect erwünscht)
    return RedirectResponse(url="/?year=2026&month=7", status_code=303)

@app.get("/bookings/", response_model=List[schemas.Booking])
def get_api_bookings(employee_id: Optional[int] = None, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    query = db.query(models.Booking)
    if user.role != models.UserRole.ADMIN:
        # Employees can only see their own bookings
        query = query.filter(models.Booking.employee_id == user.employee_id)
    elif employee_id:
        query = query.filter(models.Booking.employee_id == employee_id)
    return query.all()

@app.post("/bookings/", response_model=schemas.Booking)
def create_api_booking(booking: schemas.BookingCreate, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    if user.role != models.UserRole.ADMIN and booking.employee_id != user.employee_id:
        raise HTTPException(status_code=403, detail="You can only create bookings for yourself")
    
    # Check staffing for non-admins
    if user.role != models.UserRole.ADMIN:
        staffing = db.query(models.Staffing).filter(
            models.Staffing.project_id == booking.project_id,
            models.Staffing.employee_id == user.employee_id
        ).first()
        if not staffing:
            raise HTTPException(status_code=403, detail="You can only book hours on projects you are staffed on")

    db_booking = models.Booking(**booking.model_dump())
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
    return db_booking

@app.post("/staffings/", response_model=schemas.Staffing)
def create_staffing(staffing: schemas.StaffingCreate, db: Session = Depends(get_db), user: models.User = Depends(admin_required)):
    # Basic validation: check if project and resource exist
    project = db.query(models.Project).filter(models.Project.id == staffing.project_id).first()
    employee = db.query(models.Employee).filter(models.Employee.id == staffing.employee_id).first()
    if not project or not employee:
        raise HTTPException(status_code=404, detail="Project or Employee not found")
    
    db_staffing = models.Staffing(**staffing.model_dump())
    db.add(db_staffing)
    db.commit()
    db.refresh(db_staffing)
    return db_staffing

@app.get("/analysis/heatmap/", response_model=List[schemas.CapacityHeatmapEntry])
def get_heatmap(year: int, month: int, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    employees = db.query(models.Employee).all()
    results = []
    
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    for emp in employees:
        # 1. Total Capacity (usually 1.0 FTE, adjusted by weekly_hours if needed)
        # Assuming 40h = 1.0 FTE
        total_cap = emp.weekly_hours / 40.0
        
        # 2. Service Allocation
        service_allocs = db.query(models.ServiceAllocation).filter(models.ServiceAllocation.employee_id == emp.id).all()
        service_cap = sum(s.capacity_percent for s in service_allocs) / 100.0
        
        # 3. Staffed Capacity in this month
        staffings = db.query(models.Staffing).filter(
            models.Staffing.employee_id == emp.id,
            models.Staffing.start_date <= last_day,
            models.Staffing.end_date >= first_day
        ).all()
        
        staffed_cap = 0.0
        for s in staffings:
            # Simplistic model: if it overlaps the month, we count the FTE. 
            staffed_cap += s.capacity_fte
            
        free_cap = total_cap - service_cap - staffed_cap
        
        results.append(schemas.CapacityHeatmapEntry(
            employee_id=emp.id,
            employee_name=emp.name,
            year=year,
            month=month,
            total_capacity_fte=total_cap,
            staffed_capacity_fte=staffed_cap,
            service_capacity_fte=service_cap,
            free_capacity_fte=free_cap
        ))
        
    return results

@app.get("/ui/reports", response_class=HTMLResponse)
def ui_reports(request: Request, db: Session = Depends(get_db), user: models.User = Depends(login_required)):
    if not request.state.user:
        return RedirectResponse(url="/login")
    # 1. Projekt-Status-Verteilung
    status_counts = db.query(models.Project.status, func.count(models.Project.id)).group_by(models.Project.status).all()
    # Mappe Enum-Werte auf Anzeigenamen und stelle sicher, dass sie Strings sind
    status_map = {
        models.ProjectStatus.PLANNING: "PLANUNG",
        models.ProjectStatus.ACTIVE: "AKTIV",
        models.ProjectStatus.ON_HOLD: "ON HOLD",
        models.ProjectStatus.COMPLETED: "ABGESCHLOSSEN"
    }
    status_data = {status_map.get(s, str(s)): count for s, count in status_counts}
    
    # 2. Projekte mit kritischem Zeitverzug oder Budget-Überschreitung (Fortschritt > Zeit)
    all_projects = db.query(models.Project).filter(models.Project.status != models.ProjectStatus.COMPLETED).all()
    critical_projects = []
    sleeper_projects = []
    overdue_projects = []
    
    today = date.today()
    for p in all_projects:
        # Überfällige Projekte (Enddatum in Vergangenheit und nicht abgeschlossen)
        if p.end_date < today:
            overdue_projects.append({
                "id": p.id,
                "name": p.name,
                "end_date": p.end_date,
                "status": p.status
            })

        # Berechne zeitlichen Fortschritt
        total_days = (p.end_date - p.start_date).days
        if total_days > 0:
            elapsed_days = (today - p.start_date).days
            time_progress = max(0, min(100, (elapsed_days / total_days) * 100))
        else:
            time_progress = 100

        # Berechne IST-Stunden
        total_booked = db.query(func.sum(models.Booking.hours)).filter(models.Booking.project_id == p.id).scalar() or 0.0
        
        # Schläferprojekte: Gestartet aber keine Buchungen
        if p.start_date <= today and total_booked == 0:
            sleeper_projects.append({
                "id": p.id,
                "name": p.name,
                "start_date": p.start_date
            })

        # Berechne geplante Stunden (8h pro PT)
        planned_hours = (p.pt_intern_planned + p.pt_extern_planned) * 8.0
        
        # Fortschritt (basierend auf Stunden)
        work_progress = (total_booked / planned_hours * 100) if planned_hours > 0 else (100 if total_booked > 0 else 0)
        
        if work_progress > time_progress + 10: # Mehr als 10% Abweichung
            critical_projects.append({
                "name": p.name,
                "work_progress": round(work_progress, 1),
                "time_progress": round(time_progress, 1),
                "diff": round(work_progress - time_progress, 1)
            })
            
    # Sortiere nach höchster Abweichung
    critical_projects = sorted(critical_projects, key=lambda x: x["diff"], reverse=True)[:5]
    
    # Sortiere Schläfer nach Startdatum (älteste zuerst)
    sleeper_projects = sorted(sleeper_projects, key=lambda x: x["start_date"])[:5]
    
    # 3. Auslastung über die nächsten 6 Monate (vereinfacht)
    today = date.today()
    months = []
    utilization = []
    
    # Hole alle Mitarbeiter für Kapazitätsberechnung
    total_employees = db.query(models.Employee).count()
    total_capacity_fte = db.query(func.sum(models.Employee.weekly_hours)).scalar() or 0
    total_capacity_fte = total_capacity_fte / 40.0
    
    for i in range(6):
        target_date = today + timedelta(days=i*30)
        month_name = target_date.strftime("%b %y")
        months.append(month_name)
        
        # Staffing in diesem Monat
        first_day = target_date.replace(day=1)
        last_day = target_date.replace(day=calendar.monthrange(target_date.year, target_date.month)[1])
        
        staffed_sum = db.query(func.sum(models.Staffing.capacity_fte)).filter(
            models.Staffing.start_date <= last_day,
            models.Staffing.end_date >= first_day
        ).scalar() or 0.0
        
        utilization.append(round((staffed_sum / total_capacity_fte * 100) if total_capacity_fte > 0 else 0, 1))

    # 4. Division Verteilung
    division_counts = db.query(models.Project.division, func.count(models.Project.id)).group_by(models.Project.division).all()
    # Mappe Division-Namen
    division_data = {str(d) if d else "Unbekannt": count for d, count in division_counts}
    
    # Sicherstellen, dass die Daten für JS als Listen vorliegen, um Probleme mit .keys() zu vermeiden
    status_labels = list(status_data.keys())
    status_values = list(status_data.values())
    division_labels = list(division_data.keys())
    division_values = list(division_data.values())

    definitions = {
        "Projekte Gesamt": "Die Gesamtzahl aller Projekte im System (Planung, Aktiv, On Hold, Abgeschlossen).",
        "Aktive Projekte": "Projekte, die sich aktuell in der Umsetzung befinden (Status 'active').",
        "Aktuelle Auslastung": "Verhältnis der für den aktuellen Monat geplanten Personal-Kapazitäten (FTE) zur verfügbaren Gesamtkapazität der Mitarbeiter.",
        "Kritische Projekte": "Projekte, bei denen der Ressourcenverbrauch (Ist-Stunden) den zeitlichen Fortschritt um mehr als 10% übersteigt.",
        "Projekt-Status Verteilung": "Grafische Darstellung der Projekte aufgeteilt nach ihrem aktuellen Lebenszyklus-Status.",
        "Ressourcen-Auslastung": "Trend der geplanten Auslastung (Staffing) über die nächsten 6 Monate im Verhältnis zur Gesamtkapazität.",
        "Projekte nach Bereich": "Anzahl der Projekte gruppiert nach Fachbereichen (IT, Netzgesellschaft, etc.).",
        "Top 5 Kritische Projekte": "Liste der Projekte mit der höchsten negativen Abweichung zwischen Arbeitsfortschritt und Zeitverlauf.",
        "Schläferprojekte": "Projekte, die laut Startdatum bereits laufen sollten, aber noch keine Zeitbuchungen aufweisen.",
        "Überfällige Projekte": "Projekte, deren geplantes Enddatum in der Vergangenheit liegt, aber noch nicht abgeschlossen sind."
    }

    context = {
        "request": request,
        "active_page": "reports",
        "title": "Management Reports",
        "status_labels": status_labels,
        "status_values": status_values,
        "critical_projects": critical_projects,
        "sleeper_projects": sleeper_projects,
        "overdue_projects": sorted(overdue_projects, key=lambda x: x["end_date"]),
        "months": months,
        "utilization": utilization,
        "division_labels": division_labels,
        "division_values": division_values,
        "total_projects": db.query(models.Project).count(),
        "active_projects": db.query(models.Project).filter(models.Project.status == models.ProjectStatus.ACTIVE).count(),
        "definitions": definitions
    }
    return templates.TemplateResponse(request=request, name="reports.html", context=context)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
