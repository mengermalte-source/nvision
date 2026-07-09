from sqlalchemy import Column, Integer, String, Date, Float, ForeignKey, Enum, DateTime, Boolean
from sqlalchemy.orm import relationship, declarative_base
import enum
from datetime import datetime

Base = declarative_base()

class UserRole(enum.Enum):
    ADMIN = "admin"
    EMPLOYEE = "employee"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(Enum(UserRole), default=UserRole.EMPLOYEE)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    is_active = Column(Boolean, default=True)

    employee = relationship("Employee", back_populates="user")

class ResourceType(enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"

class ProjectStatus(enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"

class PABStatus(enum.Enum):
    EVALUATION = "evaluation"
    REVISION = "revision"
    CONFIRMED = "confirmed"
    APPROVED = "approved"

class SteeringStatus(enum.Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    NONE = "NONE"

class BudgetCategory(enum.Enum):
    INVEST = "invest"
    UNTERHALT = "unterhalt"

class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    employees = relationship("Employee", back_populates="team")

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    employees = relationship("Employee", back_populates="role")

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(Enum(ResourceType), default=ResourceType.INTERNAL)
    role_id = Column(Integer, ForeignKey("roles.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    weekly_hours = Column(Float, default=40.0)
    annual_hours_target = Column(Float, nullable=True) # Neuer Wert für Jahresplanung
    employment_start = Column(Date)
    employment_end = Column(Date, nullable=True)

    role = relationship("Role", back_populates="employees")
    team = relationship("Team", back_populates="employees")
    staffings = relationship("Staffing", back_populates="employee")
    service_allocations = relationship("ServiceAllocation", back_populates="employee")
    absences = relationship("Absence", back_populates="employee")
    user = relationship("User", back_populates="employee", uselist=False)
    bookings = relationship("Booking", back_populates="employee")

class Division(enum.Enum):
    IT = "IT"
    NETZ = "Netzgesellschaft"
    VERTRIEB = "Vertrieb"
    KRAFTWERK = "Kraftwerk"

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    business_value = Column(String, nullable=True)
    internal_number = Column(String, nullable=True)
    division = Column(String, nullable=True) # "IT", "Netzgesellschaft", "Vertrieb", "Kraftwerk"
    start_date = Column(Date)
    end_date = Column(Date)
    priority = Column(Integer, default=1) # 1 highest
    status = Column(Enum(ProjectStatus), default=ProjectStatus.PLANNING)
    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    
    # Neue Felder
    responsible_it = Column(String, nullable=True)
    responsible_fb = Column(String, nullable=True)
    pab_approval = Column(Integer, default=0) # 0 = No, 1 = Yes (Legacy)
    pab_status = Column(Enum(PABStatus), default=PABStatus.EVALUATION)
    pab_rank = Column(Integer, default=999)
    cats_number = Column(String, nullable=True)
    pt_intern_pab = Column(Float, default=0.0)
    pt_intern_planned = Column(Float, default=0.0)
    pt_extern_planned = Column(Float, default=0.0)
    economic_score = Column(Float, default=0.0) # 0.0 to 10.0
    business_case = Column(String, nullable=True)

    # Steuerungs-Felder
    steering_status = Column(Enum(SteeringStatus), default=SteeringStatus.NONE)
    steering_time = Column(Enum(SteeringStatus), default=SteeringStatus.NONE)
    steering_budget = Column(Enum(SteeringStatus), default=SteeringStatus.NONE)
    steering_quality = Column(Enum(SteeringStatus), default=SteeringStatus.NONE)
    steering_details = Column(String, nullable=True)
    steering_last_update = Column(Date, nullable=True)

    # Budget-Felder (Gesamtlaufzeit)
    budget_total_invest = Column(Float, default=0.0)
    budget_total_unterhalt = Column(Float, default=0.0)
    has_steering_board = Column(Boolean, default=False)

    staffings = relationship("Staffing", back_populates="project")
    bookings = relationship("Booking", back_populates="project")
    milestones = relationship("Milestone", back_populates="project", cascade="all, delete-orphan")
    pab_comments = relationship("ProjectComment", back_populates="project", cascade="all, delete-orphan")
    budgets = relationship("ProjectBudget", back_populates="project", cascade="all, delete-orphan")
    steering_members = relationship("Employee", secondary="project_steering_members")

class ProjectSteeringMember(Base):
    __tablename__ = "project_steering_members"
    project_id = Column(Integer, ForeignKey("projects.id"), primary_key=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), primary_key=True)

class ProjectBudget(Base):
    __tablename__ = "project_budgets"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    year = Column(Integer, index=True)
    category = Column(Enum(BudgetCategory))
    amount = Column(Float, default=0.0)

    project = relationship("Project", back_populates="budgets")

class ProjectComment(Base):
    __tablename__ = "project_comments"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    author_id = Column(Integer, ForeignKey("users.id"))
    text = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_pab_relevant = Column(Boolean, default=True)
    is_read = Column(Boolean, default=False)

    project = relationship("Project", back_populates="pab_comments")
    author = relationship("User")

class Milestone(Base):
    __tablename__ = "milestones"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    name = Column(String)
    date = Column(Date)
    description = Column(String, nullable=True)

    project = relationship("Project", back_populates="milestones")

class Staffing(Base):
    __tablename__ = "staffings"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    employee_id = Column(Integer, ForeignKey("employees.id"))
    start_date = Column(Date)
    end_date = Column(Date)
    capacity_fte = Column(Float) # 1.0 = 100%

    project = relationship("Project", back_populates="staffings")
    employee = relationship("Employee", back_populates="staffings")

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    project_id = Column(Integer, ForeignKey("projects.id"))
    date = Column(Date)
    hours = Column(Float)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    employee = relationship("Employee", back_populates="bookings")
    project = relationship("Project", back_populates="bookings")

class ServiceAllocation(Base):
    __tablename__ = "service_allocations"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    capacity_percent = Column(Float) # e.g. 20.0 for 20%
    description = Column(String, nullable=True)

    employee = relationship("Employee", back_populates="service_allocations")

class Absence(Base):
    __tablename__ = "absences"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"))
    start_date = Column(Date)
    end_date = Column(Date)
    reason = Column(String)

    employee = relationship("Employee", back_populates="absences")

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(String)
