import uvicorn
import random
import csv
import io
from fastapi import FastAPI, Depends, HTTPException, Query, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session
from datetime import date, datetime, timedelta
import calendar
from typing import List, Optional
import hashlib
from jose import JWTError, jwt

import models
import schemas

# Security Settings
SECRET_KEY = "n-vision-very-secret-key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

SQLALCHEMY_DATABASE_URL = "sqlite:///./n-vision.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="N-VISION - Project & Employee Management System")
templates = Jinja2Templates(directory="templates")

# --- Security Helpers ---
def verify_password(plain_password, hashed_password):
    return get_password_hash(plain_password) == hashed_password

def get_password_hash(password):
    return hashlib.sha256(password.encode()).hexdigest()

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

def admin_required(user: models.User = Depends(get_current_user)):
    if not user or user.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# Context Processor for templates
@app.middleware("http")
async def add_user_to_request(request: Request, call_next):
    db = SessionLocal()
    request.state.user = await get_current_user(request, db)
    db.close()
    response = await call_next(request)
    return response

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
    response.set_cookie(key="access_token", value=access_token, httponly=True)
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
        return min(progress, 100.0)
    return 0.0

# --- UI Routes ---

@app.get("/", response_class=HTMLResponse)
def ui_heatmap(request: Request, year: Optional[int] = None, db: Session = Depends(get_db)):
    if not request.state.user:
        return RedirectResponse(url="/login")
    
    if year is None: year = date.today().year
    
    heatmap_data = get_annual_heatmap(year, db)
    return templates.TemplateResponse(
        request=request, name="heatmap.html", context={
            "heatmap": heatmap_data, 
            "year": year,
            "active_page": "heatmap",
            "user": request.state.user
        }
    )

@app.get("/api/heatmap/detail/{employee_id}/{year}/{month}", response_model=schemas.CapacityDetail)
def get_capacity_detail(employee_id: int, year: int, month: int, db: Session = Depends(get_db)):
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
        staffing_details.append(schemas.StaffingDetail(
            project_name=s.project.name,
            capacity_fte=s.capacity_fte
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

def get_annual_heatmap(year: int, db: Session):
    employees = db.query(models.Employee).all()
    results = []
    
    for emp in employees:
        total_cap = emp.weekly_hours / 40.0
        service_allocs = db.query(models.ServiceAllocation).filter(models.ServiceAllocation.employee_id == emp.id).all()
        service_cap = sum(s.capacity_percent for s in service_allocs) / 100.0
        
        months_data = []
        for m in range(1, 13):
            first_day = date(year, m, 1)
            last_day = date(year, m, calendar.monthrange(year, m)[1])
            
            staffings = db.query(models.Staffing).filter(
                models.Staffing.employee_id == emp.id,
                models.Staffing.start_date <= last_day,
                models.Staffing.end_date >= first_day
            ).all()
            
            staffed_cap = sum(s.capacity_fte for s in staffings)
            free_cap = total_cap - service_cap - staffed_cap
            
            status = "ok"
            if free_cap < 0:
                status = "error"
            elif free_cap < 0.2:
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

@app.get("/ui/projects", response_class=HTMLResponse)
def ui_projects(request: Request, division: Optional[str] = None, db: Session = Depends(get_db)):
    if not request.state.user:
        return RedirectResponse(url="/login")
    
    if request.state.user.role == models.UserRole.ADMIN:
        query = db.query(models.Project)
    else:
        # Employees only see projects they are staffed on
        query = db.query(models.Project).join(models.Staffing).filter(models.Staffing.employee_id == request.state.user.employee_id)
    
    if division:
        query = query.filter(models.Project.division == division)
        
    projects = query.all()
    
    # Add progress to each project object (dynamically)
    for p in projects:
        p.progress = calculate_project_progress(p, db)

    return templates.TemplateResponse(
        request=request, name="projects.html", context={
            "projects": projects,
            "active_page": "projects",
            "user": request.state.user,
            "selected_division": division
        }
    )

@app.get("/ui/bookings", response_class=HTMLResponse)
def ui_bookings(request: Request, db: Session = Depends(get_db)):
    if not request.state.user or request.state.user.role != models.UserRole.EMPLOYEE:
        return RedirectResponse(url="/")
    
    assigned_projects = db.query(models.Project).join(models.Staffing).filter(models.Staffing.employee_id == request.state.user.employee_id).all()
    bookings = db.query(models.Booking).filter(models.Booking.employee_id == request.state.user.employee_id).order_by(models.Booking.date.desc()).all()
    
    return templates.TemplateResponse(
        request=request, name="bookings.html", context={
            "assigned_projects": assigned_projects,
            "bookings": bookings,
            "today": date.today().isoformat(),
            "active_page": "bookings",
            "user": request.state.user
        }
    )

@app.post("/ui/bookings/add")
def ui_add_booking(
    project_id: int = Form(...),
    date: date = Form(...),
    hours: float = Form(...),
    description: Optional[str] = Form(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    user = request.state.user
    if not user or user.role != models.UserRole.EMPLOYEE:
        raise HTTPException(status_code=403, detail="Only employees can book hours")
    
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
def ui_add_project_form(request: Request):
    return templates.TemplateResponse(
        request=request, name="project_add.html", context={
            "active_page": "project_add"
        }
    )

@app.post("/ui/projects/add")
def ui_add_project(
    name: str = Form(...),
    description: Optional[str] = Form(None),
    methodology: models.ProjectMethodology = Form(models.ProjectMethodology.CLASSIC),
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
    db: Session = Depends(get_db)
):
    db_project = models.Project(
        name=name,
        description=description,
        methodology=methodology,
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
def ui_edit_project_form(request: Request, project_id: int, db: Session = Depends(get_db)):
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
    methodology: models.ProjectMethodology = Form(models.ProjectMethodology.CLASSIC),
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
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    project.name = name
    project.description = description
    project.methodology = methodology
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

@app.get("/ui/projects/{project_id}", response_class=HTMLResponse)
def ui_project_detail(request: Request, project_id: int, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    progress = calculate_project_progress(project, db)
    
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
    db: Session = Depends(get_db)
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
def ui_delete_milestone(project_id: int, milestone_id: int, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
):
    db_emp = models.Employee(name=name, type=type, weekly_hours=weekly_hours, team_id=team_id, employment_start=date.today())
    db.add(db_emp)
    db.commit()
    return RedirectResponse(url="/ui/employees", status_code=303)

@app.get("/ui/employees/{employee_id}/plan", response_class=HTMLResponse)
def ui_employee_plan(request: Request, employee_id: int, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
):
    employee = db.query(models.Employee).filter(models.Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    employee.annual_hours_target = annual_hours_target
    db.commit()
    return RedirectResponse(url="/ui/employees", status_code=303)

@app.get("/ui/staffing/add", response_class=HTMLResponse)
def ui_staffing_add_form(request: Request, project_id: int, db: Session = Depends(get_db)):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    employees = db.query(models.Employee).all()
    return templates.TemplateResponse(
        request=request, name="staffing_add.html", context={
            "project": project,
            "employees": employees
        }
    )

@app.post("/ui/staffing/add")
def ui_add_staffing(
    project_id: int = Form(...),
    employee_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    capacity_fte: float = Form(...),
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
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
def get_teams(db: Session = Depends(get_db)):
    return db.query(models.Team).all()

@app.post("/teams/", response_model=schemas.Team)
def create_team(team: schemas.TeamCreate, db: Session = Depends(get_db)):
    db_team = models.Team(name=team.name)
    db.add(db_team)
    db.commit()
    db.refresh(db_team)
    return db_team

@app.get("/roles/", response_model=List[schemas.Role])
def get_roles(db: Session = Depends(get_db)):
    return db.query(models.Role).all()

@app.post("/roles/", response_model=schemas.Role)
def create_role(role: schemas.RoleCreate, db: Session = Depends(get_db)):
    db_role = models.Role(name=role.name)
    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

@app.get("/employees/", response_model=List[schemas.Employee])
def get_employees(db: Session = Depends(get_db)):
    return db.query(models.Employee).all()

@app.post("/employees/", response_model=schemas.Employee)
def create_employee(employee: schemas.EmployeeCreate, db: Session = Depends(get_db)):
    db_employee = models.Employee(**employee.model_dump())
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee

@app.get("/projects/", response_model=List[schemas.Project])
def get_projects(db: Session = Depends(get_db)):
    return db.query(models.Project).all()

@app.post("/projects/", response_model=schemas.Project)
def create_project(project: schemas.ProjectCreate, db: Session = Depends(get_db)):
    db_project = models.Project(**project.model_dump())
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project

@app.get("/staffings/", response_model=List[schemas.Staffing])
def get_staffings(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.Staffing)
    if project_id:
        query = query.filter(models.Staffing.project_id == project_id)
    return query.all()

@app.post("/seed/")
def seed_database(db: Session = Depends(get_db)):
    # ... (Seed-Logik bleibt gleich)
    # ...
    # Rückleitung zur Heatmap nach dem Seeden, wenn es über die UI kommt
    # Wir prüfen nicht explizit auf Request, da es ein POST ist.
    # Um sowohl API als auch UI zu bedienen:
    
    # 1. Clear existing data
    db.query(models.Milestone).delete()
    db.query(models.Booking).delete()
    db.query(models.Staffing).delete()
    db.query(models.ServiceAllocation).delete()
    db.query(models.Project).delete()
    db.query(models.Employee).delete()
    db.query(models.Role).delete()
    db.query(models.Team).delete()
    
    # 2. Create Teams
    teams = [models.Team(name=n) for n in ["Backend", "Frontend", "DevOps", "QA"]]
    db.add_all(teams)
    db.commit()
    for t in teams: db.refresh(t)
    
    # 3. Create Roles
    roles = [models.Role(name=n) for n in ["Senior Dev", "Junior Dev", "Architect", "PO"]]
    db.add_all(roles)
    db.commit()
    for r in roles: db.refresh(r)
    
    # 4. Create Resources
    names = [
        "Alice Tech", "Bob Builder", "Charlie Cloud", "Diana Data", "Erik Engineering",
        "Fiona Frontend", "George Graph", "Hannah Hardware", "Ian Infrastructure", "Julia Java",
        "Kevin Kernel", "Laura Logic", "Michael Mobile", "Nina Network", "Oscar Ops",
        "Paula Python", "Quentin QA", "Rachel React", "Steve SQL", "Tina Testing",
        "Umar UI", "Vera UX", "Walter Web", "Xenia XML", "Yorick YAML", "Zoe Zero",
        "Adam Agile", "Bella Backup", "Chris Code", "Daisy Docker", "Edward Encryption",
        "Fred Firewall", "Gina Git", "Harry HTML", "Iris IoT", "Jack JSON",
        "Kira Kubernetes", "Liam Linux", "Mona Monitoring", "Noah Node", "Olivia OAuth",
        "Peter PHP", "Quinn Query", "Rose REST", "Sam Scrum", "Tara Token",
        "Ursula Ubuntu", "Victor Vim", "Wendy WiFi", "Xander XSS", "Yvonne Yubikey", "Zack Z-Wave",
        "Arthur API", "Beatrice Bash", "Cedric CSS", "Doris DNS", "Evan E-Mail",
        "Felicia FTP", "Gilbert GPU", "Hilda HTTP", "Isaac IP", "Jenny Jenkins",
        "Kurt Kafka", "Lilly LDAP", "Max Markdown", "Nelly NFS", "Otto OOP",
        "Patty Pearl", "Quincy Qubit", "Ron Ruby", "Sally SSH", "Tom TCP",
        "Ulysses UDP", "Valerie VPN", "Will WSDL", "Xaver XPATH", "Yasmin Yacc", "Zelda Zip",
        "Albert Algorithm", "Brenda Binary", "Conrad Compiler", "Debbie Debug", "Elliot Editor",
        "Flora Float", "Gavin Gateway", "Holly Hash", "Ivan Integer", "Joy Joystick",
        "Karl Keyboard", "Linda Linker", "Mark Macro", "Nancy Null", "Oliver Octal",
        "Paul Pointer", "Queenie Queue", "Robert Router", "Sarah Stack", "Tim Thread"
    ]
    
    # Ergänze falls nötig auf 100
    while len(names) < 100:
        names.append(f"Mitarbeiter {len(names) + 1}")

    all_employees = []
    for i, name in enumerate(names):
        emp_type = models.ResourceType.INTERNAL if i % 5 != 0 else models.ResourceType.EXTERNAL
        emp = models.Employee(
            name=name,
            type=emp_type,
            role_id=roles[i % len(roles)].id,
            team_id=teams[i % len(teams)].id,
            weekly_hours=40 if emp_type == models.ResourceType.INTERNAL else 20,
            employment_start=date(2023, 1, 1) + timedelta(days=i*10)
        )
        all_employees.append(emp)
    
    db.add_all(all_employees)
    db.commit()
    for emp in all_employees: db.refresh(emp)
    
    res1, res2, res3 = all_employees[0], all_employees[1], all_employees[2]
    
    # 5. Create Projects from raw data
    random.seed(42)  # For reproducible mixing
    raw_csv_data = """project_code;name;description;bereich;typ;status;priority;start_date;end_date;responsible_it;responsible_business;pab_approved;cats_order;planned_internal_pt;planned_external_pt;actual_pt;source_hint
P.Z.23198-01;Indidividuelle Changes/Kleinmaßnahmen (< 10 PT);IT;;Ja;;;;;;;;27030137;;;;Aufträge zu Maßnahmen
P.Z.23211-04;Projektvorklärungen Fachbereiche;IT;;Ja;;;;;;;;;;;;Aufträge zu Maßnahmen
P.Z.23121-01;Weiterentwicklung NIS inkl MGC;NNG;;Ja;;;;;Bernd Hübner;;;27028577;;;;Aufträge zu Maßnahmen
P.Z.23121-19;MGC Update;NNG;;Ja;;;;;Stephan Danhauser;;;27030336;;;;Aufträge zu Maßnahmen
P.Z.23121-02;Weiterentwicklung Netzrelevante SW;NNG;;Ja;;;;;Bernd Hübner;;;27028579;;;;Aufträge zu Maßnahmen
P.Z.23121-20;Umorganisation NE, KR, LO;NNG;;Ja;;;;;Martin Zwanzger;;;27030335;;;;Aufträge zu Maßnahmen
W.Z.23121-01;Weiterentwicklung Portale (netz agil);NNG;;Ja;;;;;Tobias Neubig;;;51127661;;;;Aufträge zu Maßnahmen
W.Z.23121-05;Weiterentwicklung Portale (Netz-Automaten) ehemals Kundenreise;NNG;;Ja;;;;;Mira Bollmann;;;51127662;;;;Aufträge zu Maßnahmen
W.Z.23121-04;Netzkundenportal - Kundenkonto;NNG;;Ja;;;;;Mira Bollmann;;;51127668;;;;Aufträge zu Maßnahmen
P.Z.23121-02;OMS Vorlagenmigration;NNG;;;;;;;Viktor Schuller;;;27030396;;;;Aufträge zu Maßnahmen
P.Z.23121-04;Weiterentwicklung Netztechnik - Robuste Kommunikation;NNG;;Ja;;;;;Gerhard Ploß;;;27028583;;;;Aufträge zu Maßnahmen
P.Z.23121-04;Weiterentwicklung Netztechnik - Maßnahmenkatalog ÜNB;NNG;;Ja;;;;;Gerhard Ploß;;;27029559;;;;Aufträge zu Maßnahmen
P.Z.23121-05;Weiterentwicklung SAP Core;NNG;;Nein;;;;;Jakob Volkert;;;-;;;;Aufträge zu Maßnahmen
P.Z.23121-06;Weiterentwicklung Digitalisierung Netze;NNG;;;;;;;Martin Zwanzger;;;0;;;;Aufträge zu Maßnahmen
P.Z.23121-23;Redispatch BNetzA Meldung;NNG;;Ja;;;;;Malte Menger;;;27030245;;;;Aufträge zu Maßnahmen
P.Z.23121-18;Weiterentwicklung Digitalisierung PoC Redispatch Bündel;NNG;;Ja;;;;;Malte Menger;;;27030337;;;;Aufträge zu Maßnahmen
P.Z.23121-21;Maßnahme KI-gestütztes System zur Verbesserung der telefonischen Erreichbarkeit bei NNG-NK;NNG;;;;;;;;;;27030542;;;;Aufträge zu Maßnahmen
P.Z.23121-22;Effiziente Anrufsteuerung für Störungsnummern;NNG;;;;;;;Matthias Gottschalk;;;27030556;;;;Aufträge zu Maßnahmen
W.Z.23121-06;NEOS Neuausrichtung Prozess- und Systemlandschaft - Umsetzung Lovion;NNG;;Ja;;;;;Bernd Hübner;;;51142992;;;;Aufträge zu Maßnahmen
W.Z.23121-07;Webpräsenzen NNG;NNG;;Ja;;;;;Stefan Golker;;;51155946;;;;Aufträge zu Maßnahmen
P.Z.23132-38;Umsetzung §10c EEG;EPuS (NNG);;Ja;;;;;Stefan Riedel;;;27030399;;;;Aufträge zu Maßnahmen
?;EEG Novelle 2025;EPuS (NNG);;Nein;;;;;;;;0;;;;Aufträge zu Maßnahmen
?;Marktintegration von Speichern und Ladepunkte;EPuS (NNG);;Nein;;;;;;;;0;;;;Aufträge zu Maßnahmen
P.Z.23132-33;SmartSim;EPuS (NNG);;Ja;;;;;Marcel Fuchs;;;27028749;;;;Aufträge zu Maßnahmen
P.Z.23132-40;KI-gestützte Automatisierung des Posteingangs bei NNG-NK und NKS;EPuS (NNG);;;;;;;Malte Menger;;;27030538;;;;Aufträge zu Maßnahmen
P.Z.23132-41;Automatisierte Vorsortierung von Mail-Anfragen für NNG-KR (AIAS & SAP CI);EPuS (NNG);;;;;;;Malte Menger;;;27030539;;;;Aufträge zu Maßnahmen
NN;ProNet-BPL;EPuS (NNG);;;;;;;NN;;;0;;;;Aufträge zu Maßnahmen
P.Z.23132-47;IS/U Prozessdokumentation & Qualitätssicherung (AReS VNB/MSB - Vorprojekt);EPuS (NNG);;;;;;;Stephan Peccabin;;;NN;;;;Aufträge zu Maßnahmen
P.Z.23121-Neu2;ACRM-Lösungsevaluierung;NNG;;;;;;;Stephan Peccabin;;;;;;;Aufträge zu Maßnahmen
P.Z.23131-01;Weiterentwicklung WA Asset;WA;;Ja;;;;;Dimitri Shumilin;;;27027428;;;;Aufträge zu Maßnahmen
P.Z.23131-02;Weiterentwicklung SAP - Systemumstellungen;WA;;Ja;;;;;Christine Geißler;;;27028246;;;;Aufträge zu Maßnahmen
P.Z.23131-03;Weiterentwicklung technische Anlagen Austausch Endgeräte;WA;;Ja;;;;;Gerhard Ploß;;;27027677;;;;Aufträge zu Maßnahmen
P.Z.23132-01;Formatanpassung;NKS;;Ja;;;;;Stefan Riedel;;;27028667;;;;Aufträge zu Maßnahmen
P.Z.23132-03;Serviceverantwortung NKS (Betrieb IS-U);NKS;;Ja;;;;;Stefan Riedel;;;27028671;;;;Aufträge zu Maßnahmen
P.Z.23132-43;AMS EWS Transition;NKS;;;;;;;Stephan Peccabin;;;27030548;;;;Aufträge zu Maßnahmen
P.Z.23132-08;AReS - Vorprojekt Stabilisierung und Datenbereinigung;NKS;;Ja;;;;;Stephan Peccabin;;;27030112;;;;Aufträge zu Maßnahmen
P.Z.23132-37;Umsetzung eRechnung (+ E-Invoicing);NKS;;Ja;;;;;Stefan Riedel;;;27030362;;;;Aufträge zu Maßnahmen
P.Z.23132-28;iMSys und CLS;NKS;;Ja;;;;;Christian Binder;;;27029784;;;;Aufträge zu Maßnahmen
P.Z.23132-44;SteuerX (Nachfolgeprojekt iMSys und CLS);NKS;;;;;;;Christian Binder;;;27030735;;;;Aufträge zu Maßnahmen
P.Z.23132-35;RPA Wechsel auf Plattform der Thüga-Gruppe;NKS;;Ja;;;;;Norbert Knörr;;;27030250;;;;Aufträge zu Maßnahmen
P.Z.23132-10;Messdatenmanagementsystem (CDM);NKS;;Ja;;;;;Marcel Fuchs;;;27028685;;;;Aufträge zu Maßnahmen
P.Z.23129-05;Emissionsdatenbank (Standardisiertes Reporting mit Datenplattform);NKG;;zurückgestellt;;;;;Malte Menger;;;0;;;;Aufträge zu Maßnahmen
P.Z.23129-06;Lastmanagement;NKG;;Ja;;;;;OS;;;27030543;;;;Aufträge zu Maßnahmen
P.Z.23112-01;Aktive Neukundenakquise, UseCase1;NV;;Ja;;;;;Attila Németh;;;27030369;;;;Aufträge zu Maßnahmen
P.Z.23112-25;Individualkundenportal, UseCase7;NV;;Ja;;;;;Christian Dormann;;;27030371;;;;Aufträge zu Maßnahmen
P.Z.23112-24;Dynamischer Tarif, UseCase2;NV;;Ja;;;;;Andreas Hellmuth;;;27030134;;;;Aufträge zu Maßnahmen
P.Z.23112-23;Zeitreihenmanagement, UseCase3;NV;;Ja;;;;;Malte Menger;;;27029975;;;;Aufträge zu Maßnahmen
P.Z.23112-31;Flexibilitätsvermerkung, UseCase5;NV;;;;;;;Dankwart-Hans Pieldner;;;27030544;;;;Aufträge zu Maßnahmen
P.Z.23112-27;Einführung einer Datenplattform - Erster Projektteil;NV;;Ja;;;;;NN;;;27030373;;;;Aufträge zu Maßnahmen
P.Z.23112-17;Digitalisierung Auskömmlichkeit;NV;;Ja;;;;;Malte Menger;;;27029569;;;;Aufträge zu Maßnahmen
P.Z.23112-26;Applikation NV-BA auf ZENIT;NV;;Ja;;;;;Ralph Beier;;;27030372;;;;Aufträge zu Maßnahmen
P.Z.23132-42;SLP Ausrollung Lieferant Strom;EPuS (NV);;;;;;;Helena Henkel;;;27030546;;;;Aufträge zu Maßnahmen
P.Z.23132-29;Umstellung Geschäftspartnerarten;EPuS (NV);;;;;;;Stefan Riedel;;;27029987;;;;Aufträge zu Maßnahmen
P.Z.23125-15;56 - Weiterentwicklung von e-learning & CBT;VAG-FS;;zurückgestellt;;;;;Zwanzger, Martin;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-01;7 - Erneuerung WLAN U2/U3;VAG-FA;;Nein (Q1 2027);;;;;Grimm;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-05;Weiterentwicklung der SAP-Anwendung;VAG-FA;;Ja;;;;;Volkert;;;27028607;;;;Aufträge zu Maßnahmen
P.Z.23125-40;Weiterentwicklung FITS ehemals Umstieg auf neues BDE (inkl. Machbarkeit);VAG-FA;;Ja;;;;;Volkert;;;PT extern;;;;Aufträge zu Maßnahmen
P.Z.23125-36;277 (Anpassung des aktuellen Kommunikationswegs sowie ACI-Segmentierung des IT-Services SIBASExpert);VAG-WS;;Nein (Q4);;;;;Spick;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-44;Implementierung eines KI gestützten Prognosemodells zur Schmierung von Schienen-Fahrzeugen;VAG-WS;;zurückgestellt;;;;;Menger;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-18;172 - technischer Support vag.de und Subdomains event.vag.de, opendata.vag.de;VAG - MK;;Ja;;;;;Neukamm;;;27028633;;;;Aufträge zu Maßnahmen
P.Z.23125-19;178 - Mobilitätsplattform;VAG - MK;;Ja;;;;;Wenig;;;27028635;;;;Aufträge zu Maßnahmen
P.Z.23125-20;143-Weiterentwicklung CMS LUKAS;VAG-SB;;Ja;;;;;Neukamm;;;27028637;;;;Aufträge zu Maßnahmen
P.Z.23125-21;81 - Vertriebshintergrundsystem PTnova (Klassik);VAG-VE;;Ja;;;;;Streng;;;27028639;;;;Aufträge zu Maßnahmen
P.Z.23125-24;155 - MeinAbo (AboOnline);VAG-VE;;Ja;;;;;Schütz;;;27028645;;;;Aufträge zu Maßnahmen
P.Z.23125-45;Neubeschaffung Plattform AboOnline - Geschäftskunden;VAG-VE;;;;;;;Schütz;;;27030381;;;;Aufträge zu Maßnahmen
neu;Entwicklung eines BMS-Systems mit LLM-System;VAG-WB;;;;;;;Zwanzger;;;0;;;;Aufträge zu Maßnahmen
neu;Neugestaltung Paledo-Systemlandschaft;VAG-WB;;;;;;;tbd;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-26;152 - Betriebshof-Management-System Bus (Energieeffizient - eBus-Strategie);VAG-WB;;Nein (Q3);;;;;Zwanzger;;;27028649;;;;Aufträge zu Maßnahmen
P.Z.23125-41;KI-Unterstützung für die effiziente Bearbeitung von Kundenanliegen;VAG-MK/ VAG-VE;;Ja;;;;;Jürgen Wenig;;;27029788;;;;Aufträge zu Maßnahmen
P.Z.23125-23;83 (Onlineservices (Onlineshop und mobile App));VAG-VE;;Ja;;;;;Neukamm;;;27028643;;;;Aufträge zu Maßnahmen
neu;[VAG-FA] - SAM (Schaden- und Anwendungsmanagement);VAG-FA;;;;;;;Edler;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-46;VAG - Betriebsleistungsstatistik;VAG-FA;;;;;;;Edler;;;27030549;;;;Aufträge zu Maßnahmen
P.Z.23125-13;260 - Ela-Video Migration auf Prozessnetz;VAG-FA;;Ja;;;;;Fabian Böhm;;;27028623;;;;Aufträge zu Maßnahmen
VAG2027;Firewall Prozessnetz U-Bahn;VAG-FA;;;;;;;Fabian Böhm;;;0;;;;Aufträge zu Maßnahmen
P.Z.23125-39;WPA2-Umsetzung U1/U2/U3;VAG-FA;;;;;;;Grimm;;;27030382;;;;Aufträge zu Maßnahmen
P.Z.23125-43;274 (POC - Machbarkeitsstudie zur Nutzung des SDA-Prozessnetz);VAG-FA;;in Klärung;;;;;Schillinger;;;27029791;;;;Aufträge zu Maßnahmen
P.Z.23125-47;Ablösung von Interplan Modul Mietwagenabrechnung und Beschaffung eines Nachfolgetools;VAG-PL;;;;;;;Edler;;;nn;;;;Aufträge zu Maßnahmen
P.Z.23117-20;Konsolidierung Zeiterfassungssysteme;PE;;Ja;;;;;Johanna Reitzer;;;27027402;;;;Aufträge zu Maßnahmen
P.Z.23117-16;Neubeschaffung Personalverwaltung;PE;;abgeschlossen;;;;;Johanna Reitzer;;;27028097;;;;Aufträge zu Maßnahmen
P.Z.23134-04;S4 - Ablösung Glania Tools;NIM;;;;;;;Jürgen Wenig;;;27030734;;;;Aufträge zu Maßnahmen
P.Z.23117-17;E-Mail für VAG-Fahrer und Werkstattmitarbeiter;PE;;Ja;;;;;Felix Doll;;;27029437;;;;Aufträge zu Maßnahmen
P.Z.23128-01;Einführung Software Schadensfallmanagement;KVN;;Ja;;;;;Stephan Kroppe;;;27029333;;;;Aufträge zu Maßnahmen
P.Z.23132-neu2;Automatisierung Haustarif;EPuS (PE);;;;;;;Andreas Hellmuth;;;0;;;;Aufträge zu Maßnahmen
P.Z.23130-02;Umsetzung DORA;RZK;;zurückgestellt;;;;;Eberhard Meyer;;;27029557;;;;Aufträge zu Maßnahmen
P.Z.23123-19;Einführung SAP Datasphere;RW;;abgeschlossen;;;;;Ines Khosravi;;;27030292;;;;Aufträge zu Maßnahmen
P.Z.23212-57;Transition SIEM/SOC;IT-IN;;ja;;;;;Bastian Voigt;;;20102806;;;;Aufträge zu Maßnahmen
P.Z.23212-74;Rechenzentrum Kafkastraße;IT-IN-BT;;ja;;;;;Grégoire Verfaillie;;;20078800;;;;Aufträge zu Maßnahmen
P.Z.23215-04;Einführung Copilot;IT;;ja;;;;;Julia Kuhla;;;20103041;;;;Aufträge zu Maßnahmen
P.Z.23212-89;AIX Außerbetriebnahme (vorher: AIX Ablöse);IT-IN-BT;;ja;;;;;Achim Landsberger;;;20097953;;;;Aufträge zu Maßnahmen
P.Z.23212-90;Thüga Ausschreibung – Hardware und Hardwarenahe Dienstleistungen;IT-IN-AP;;ja;;;;;Thomas Walter;;;20097751;;;;Aufträge zu Maßnahmen
P.Z.23215-01;Umsetzung Access Netzwerk;IT-IN-NK;;ja;;;;;Patrick Seubelt;;;20103027;;;;Aufträge zu Maßnahmen
P.Z.23212-28;Erneuerung WLAN-Infrastruktur;IT-IN-NK;;Ja;;;;;Tom Kreuzig;;;20084065;;;;Aufträge zu Maßnahmen
P.Z.23212-65;HAS+ VAG;NIM;;ja;;;;;Tom Kreuzig;;;20089563;;;;Aufträge zu Maßnahmen
P.Z.23215-02;SASE/Zero-Trust Strategie;IT-IN-NK;;ja;;;;;Michael Ringler;;;20103040;;;;Aufträge zu Maßnahmen
Neu;Redesign VAG Backbone Router;IT-IN-NK;;Zürückgestellt;;;;;Wolfgang Grimm;;;0;;;;Aufträge zu Maßnahmen
P.Z.23212-82;Auswahl eines neuen Contact-Centers (vorher: Ausschreibung ACD Telefonie);IT-IN-NK;;Ja;;;;;Christian Preiß;;;20096731;;;;Aufträge zu Maßnahmen
P.Z.23212-83;S/4Future;IT-ER;;Ja;;;;;Klaus Wirthmann;;;20096732;;;;Aufträge zu Maßnahmen
P.Z.23212-93;Refactoring energiewirtschaftliche Systeme, UseCase8;EPuS (IT);;abgeschlossen;;;;;Stefan Riedel (temporär);;;20098312;;;;Aufträge zu Maßnahmen
P.Z.23212-96;Azure Local;IT-IN;;Ja;;;;;Napokoj Stephan;;;20103018;;;;Aufträge zu Maßnahmen
P.Z.23215-06;Berechtigungs Management PoC Tenfold (Prüfung einer Ablöse Varonis);IT-IN-BT;;Ja;;;;;Manuel Siegl;;;20103969;;;;Aufträge zu Maßnahmen
P.Z.23212-97;Konzept und Umsetzung zur Abschaffung UMS;IT-IN-NK;;Ja;;;;;Matthias Gottschalk;;;20103019;;;;Aufträge zu Maßnahmen
P.Z.23212-82;Test und Upgrade der XPERT Kommunikationslösung in den NNG Leitstellen;IT-IN-NK;;Ja;;;;;Matthias Gottschalk;;;20104510;;;;Aufträge zu Maßnahmen
P.Z.23215-07;Umsetzung Rufbereitschaftskonzept;IT-IN-NK;;Ja;;;;;Christian Preiß;;;20103968;;;;Aufträge zu Maßnahmen
-;Refactoring BKA;IT-ER;;Nein;;;;;Claudia Deubler;;;0;;;;Aufträge zu Maßnahmen
UX/UI News;UX/UI News;IT-PA-AE;;;;;;;;;;0;;;;Aufträge zu Maßnahmen
P.Z.23215-05;PO2CI;IT-PA-MA;;;;;;;Peter Bamberger;;;20103659;;;;Aufträge zu Maßnahmen
-;Leichtgewichtiger Innovationsprozess;IT-PA-AE;;;;;;;;;;0;;;;Aufträge zu Maßnahmen
P.Z.23215-03;Digital Workplace Excellence;IT-IN-AP;;Ja;;;;;Verena Beck;;;20103042;;;;Aufträge zu Maßnahmen
P.Z.23212-95;Automatisierung Userneuanlage Prozess (Umsetzung);IT-IN;;Ja;;;;;Frank Schlicker;;;20098712;;;;Aufträge zu Maßnahmen
P.Z.23212-91;Redesign Mailflow und Ablösung Sophos Gateway;0;;0;;;;;0;;;20098313;;;;Aufträge zu Maßnahmen
P.Z.23212-77;Umstellung MobileIron zu Intune;IT-IN-AP;;Ja;;;;;Philipp Melchior;;;20091387;;;;Aufträge zu Maßnahmen
P.Z.23212-98;SAP-NFS;IT-IN-BT;;Ja;;;;;Felix Doll;;;20103021;;;;Aufträge zu Maßnahmen
P.Z.23212-99;REGULAR Phase I;IT-INS;;Ja;;;;;Herbert Motzel;;;20103023;;;;Aufträge zu Maßnahmen
P.Z.23207-05;Windows 25H2;IT-IN-AP;;;;;;;Philipp Melchior;;;20103970;;;;Aufträge zu Maßnahmen
P.Z.23215-09;Ablösung Oracle Java;IT;;;;;;;Martin Lüdecke;;;20104509;;;;Aufträge zu Maßnahmen
P.Z.23215-10;Copilot Agenten Basics;IT;;;;;;;Julia Kuhla;;;20104507;;;;Aufträge zu Maßnahmen
P.Z.23215-08;Einführung Tenfold;IT-IN-BT;;;;;;;Manuel Siegl;;;20104508;;;;Aufträge zu Maßnahmen
bisher PE;E-Mail für VAG-Fahrer und Werkstattmitarbeiter;IT-IN-BT;;?;;;;;Felix Doll;;;;;;;Aufträge zu Maßnahmen
P.Z.23212-94;Jira/Confluence Cloud;IT-PA-MA;;Ja;;;;;Julia Geist;;;20098708;;;;Aufträge zu Maßnahmen"""

    # 5. Create Projects from raw data
    random.seed(42)  # For reproducible mixing
    reader = csv.DictReader(io.StringIO(raw_csv_data), delimiter=';')
    all_imported_projects = []
    
    divisions = ["IT", "Netzgesellschaft", "Vertrieb", "Kraftwerk"]
    
    for i, row in enumerate(reader):
        # Mapping rules
        name = row['name']
        internal_number = row['project_code']
        
        # Durchmischte Zuweisung der Bereiche (reproduzierbar durch seed)
        division = random.choice(divisions)
        
        # Status mapping
        status_raw = row['pab_approved'].lower()
        if "ja" in status_raw:
            status = models.ProjectStatus.ACTIVE
        elif "abgeschlossen" in status_raw:
            status = models.ProjectStatus.COMPLETED
        elif "zurückgestellt" in status_raw:
            status = models.ProjectStatus.ON_HOLD
        else:
            status = models.ProjectStatus.PLANNING
            
        # Priority mapping (P1-P4)
        priority_raw = row.get('priority', '')
        if priority_raw and priority_raw.isdigit():
            priority = int(priority_raw)
        else:
            # Zufällige Priorität 1-4 (reproduzierbar durch seed)
            priority = random.randint(1, 4)

        p = models.Project(
            name=name,
            description=f"Automatischer Import für Projekt {name}.",
            methodology=models.ProjectMethodology.AGILE if i % 2 == 0 else models.ProjectMethodology.CLASSIC,
            business_value="Hoher strategischer Wert für die Digitalisierungsstrategie.",
            internal_number=internal_number,
            division=division,
            status=status,
            priority=priority,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            responsible_it=row['responsible_it'],
            responsible_fb=row['responsible_business'],
            cats_number=row['cats_order'],
            pab_approval=1 if "ja" in status_raw else 0
        )
        all_imported_projects.append(p)
    
    db.add_all(all_imported_projects)
    db.commit()
    for p in all_imported_projects: db.refresh(p)

    # Meilensteine für alle Projekte
    for i, p in enumerate(all_imported_projects):
        # Variierende Daten für Meilensteine
        m1 = models.Milestone(project_id=p.id, name="Projekt-Kickoff", date=p.start_date + timedelta(days=14), description="Initiales Meeting")
        m2 = models.Milestone(project_id=p.id, name="Konzept-Phase", date=p.start_date + timedelta(days=90), description="Abnahme Konzept")
        m3 = models.Milestone(project_id=p.id, name="Go-Live", date=p.end_date - timedelta(days=60), description="Produktivsetzung")
        db.add_all([m1, m2, m3])
        
        # Optional: Für jedes 3. Projekt einen zusätzlichen Meilenstein
        if i % 3 == 0:
            m4 = models.Milestone(project_id=p.id, name="Zwischenbericht", date=p.start_date + timedelta(days=180), description="Status-Update")
            db.add(m4)
    db.commit()
    
    # Referenzprojekte für Staffing
    p1 = all_imported_projects[0]
    p2 = all_imported_projects[2]
    
    # 6. Create Staffing
    # Wir weisen ALLEN Mitarbeitern Projekte zu, um eine ordentliche Auslastung zu zeigen.
    # Einige Projekte werden "vollgebucht".
    staffings = []
    
    # Bestimme einige Projekte, die "voll" werden sollen (z.B. die ersten 10)
    full_projects = all_imported_projects[:10]
    
    for i, emp in enumerate(all_employees):
        # Jedem Mitarbeiter 1-3 Projekte zuweisen
        num_projects = random.randint(1, 3)
        
        # Sicherstellen, dass die "full_projects" bevorzugt belegt werden, wenn i klein ist
        if i < 40:
             selected_projects = random.sample(full_projects, min(num_projects, len(full_projects)))
             # Eventuell noch ein zufälliges dazu
             if len(selected_projects) < num_projects:
                 remaining = [p for p in all_imported_projects if p not in selected_projects]
                 selected_projects.extend(random.sample(remaining, num_projects - len(selected_projects)))
        else:
             selected_projects = random.sample(all_imported_projects, num_projects)

        for proj in selected_projects:
            # Wenn es eines der "full_projects" ist, geben wir mehr Kapazität
            if proj in full_projects:
                cap = round(random.uniform(0.3, 0.6), 1)
            else:
                cap = round(random.uniform(0.05, 0.3), 1)
                
            s = models.Staffing(
                project_id=proj.id,
                employee_id=emp.id,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                capacity_fte=cap
            )
            staffings.append(s)
    db.add_all(staffings)
    
    # 7. Service Allocation (Linienaufgaben)
    # Alle Mitarbeiter haben etwas Grundlast in der Linie (10-20%)
    for emp in all_employees:
        db.add(models.ServiceAllocation(
            employee_id=emp.id, 
            capacity_percent=float(random.choice([10, 15, 20])), 
            description="Linienaufgaben / Grundlast"
        ))
    
    # 8. Buchungen (Ist-Stunden) erzeugen
    # Um Fortschritt in Projekten zu zeigen, brauchen wir Buchungen.
    # Wir buchen für das erste Halbjahr 2026.
    bookings = []
    current_date = date(2026, 1, 2) # Start im Januar
    end_booking_date = date(2026, 7, 1)
    
    # Wir nehmen eine Stichprobe von Mitarbeitern und Projekten für Buchungen, 
    # um die DB nicht zu sprengen, aber genug für "Progress" zu haben.
    for s in staffings[:150]: # Erste 150 Staffings bekommen Buchungen
        # Buche jede Woche 4 Stunden auf dieses Projekt für 20 Wochen
        for week in range(20):
            booking_date = s.start_date + timedelta(weeks=week, days=random.randint(0, 4))
            if booking_date < end_booking_date:
                # Stunden basierend auf FTE (vereinfacht)
                hours = s.capacity_fte * 40 * random.uniform(0.8, 1.2)
                b = models.Booking(
                    employee_id=s.employee_id,
                    project_id=s.project_id,
                    date=booking_date,
                    hours=round(hours, 1),
                    description="Projektarbeit gemäß Staffing"
                )
                bookings.append(b)
    
    db.add_all(bookings)
    db.commit()

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

@app.post("/staffings/", response_model=schemas.Staffing)
def create_staffing(staffing: schemas.StaffingCreate, db: Session = Depends(get_db)):
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
def get_heatmap(year: int, month: int, db: Session = Depends(get_db)):
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

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
