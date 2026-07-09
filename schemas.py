from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from typing import Optional, List
from models import ResourceType, ProjectStatus, UserRole, PABStatus, SteeringStatus, BudgetCategory

class MilestoneBase(BaseModel):
    name: str
    date: date
    description: Optional[str] = None
    is_completed: bool = False

class MilestoneCreate(MilestoneBase):
    project_id: int

class Milestone(MilestoneBase):
    id: int
    project_id: int
    model_config = ConfigDict(from_attributes=True)

class UserBase(BaseModel):
    username: str
    role: UserRole
    employee_id: Optional[int] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class ProjectCommentBase(BaseModel):
    text: str
    is_pab_relevant: bool = True

class ProjectCommentCreate(ProjectCommentBase):
    project_id: int

class ProjectComment(ProjectCommentBase):
    id: int
    project_id: int
    author_id: int
    created_at: datetime
    author: User
    model_config = ConfigDict(from_attributes=True)

class ProjectBudgetBase(BaseModel):
    year: int
    category: BudgetCategory
    amount: float

class ProjectBudgetCreate(ProjectBudgetBase):
    project_id: int

class ProjectBudget(ProjectBudgetBase):
    id: int
    project_id: int
    model_config = ConfigDict(from_attributes=True)

class BookingBase(BaseModel):
    employee_id: int
    project_id: int
    date: date
    hours: float
    description: Optional[str] = None

class BookingCreate(BookingBase):
    pass

class Booking(BookingBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class TeamBase(BaseModel):
    name: str

class TeamCreate(TeamBase):
    pass

class Team(TeamBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class RoleBase(BaseModel):
    name: str

class RoleCreate(RoleBase):
    pass

class Role(RoleBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class EmployeeBase(BaseModel):
    name: str
    type: ResourceType
    weekly_hours: float
    annual_hours_target: Optional[float] = None
    employment_start: date
    employment_end: Optional[date] = None
    role_id: Optional[int] = None
    team_id: Optional[int] = None

class EmployeeCreate(EmployeeBase):
    pass

class Employee(EmployeeBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    business_value: Optional[str] = None
    internal_number: Optional[str] = None
    division: Optional[str] = None
    start_date: date
    end_date: date
    priority: int = 1
    status: ProjectStatus = ProjectStatus.PLANNING
    manager_id: Optional[int] = None
    responsible_it: Optional[str] = None
    responsible_fb: Optional[str] = None
    pab_approval: bool = False
    pab_status: PABStatus = PABStatus.EVALUATION
    pab_rank: int = 999
    cats_number: Optional[str] = None
    pt_intern_pab: float = 0.0
    pt_intern_planned: float = 0.0
    pt_extern_planned: float = 0.0
    economic_score: float = 0.0
    business_case: Optional[str] = None
    steering_status: SteeringStatus = SteeringStatus.NONE
    steering_time: SteeringStatus = SteeringStatus.NONE
    steering_budget: SteeringStatus = SteeringStatus.NONE
    steering_quality: SteeringStatus = SteeringStatus.NONE
    steering_details: Optional[str] = None
    steering_last_update: Optional[date] = None
    budget_total_invest: float = 0.0
    budget_total_unterhalt: float = 0.0

class ProjectCreate(ProjectBase):
    pass

class Project(ProjectBase):
    id: int
    progress: Optional[float] = 0.0 # Calculated field
    milestones: List[Milestone] = []
    pab_comments: List[ProjectComment] = []
    budgets: List[ProjectBudget] = []
    model_config = ConfigDict(from_attributes=True)

class StaffingBase(BaseModel):
    project_id: int
    employee_id: int
    start_date: date
    end_date: date
    capacity_fte: float

class StaffingCreate(StaffingBase):
    pass

class Staffing(StaffingBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

class CapacityHeatmapEntry(BaseModel):
    employee_id: int
    employee_name: str
    year: int
    month: int
    total_capacity_fte: float
    staffed_capacity_fte: float
    service_capacity_fte: float
    free_capacity_fte: float

class MonthlyCapacity(BaseModel):
    month: int
    staffed_capacity_fte: float
    service_capacity_fte: float
    free_capacity_fte: float
    status: str # "ok", "warning", "error"

class AnnualHeatmapEntry(BaseModel):
    employee_id: int
    employee_name: str
    year: int
    total_capacity_fte: float
    months: List[MonthlyCapacity]

class StaffingDetail(BaseModel):
    project_name: str
    capacity_fte: float
    booked_hours: float = 0.0

class CapacityDetail(BaseModel):
    employee_name: str
    year: int
    month: int
    total_capacity_fte: float
    service_capacity_fte: float
    staffings: List[StaffingDetail]
    free_capacity_fte: float

class ConflictInfo(BaseModel):
    employee_name: str
    month: int
    year: int
    total_fte: float
    other_projects: List[str]

class ExtensionCheckResponse(BaseModel):
    has_conflicts: bool
    conflicts: List[ConflictInfo]
