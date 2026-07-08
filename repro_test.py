import requests
from datetime import date

BASE_URL = "http://localhost:8000"

def test_nvision():
    # 1. Create Team
    team = requests.post(f"{BASE_URL}/teams/", json={"name": "Cloud Platform"}).json()
    print(f"Team created: {team}")

    # 2. Create Role
    role = requests.post(f"{BASE_URL}/roles/", json={"name": "DevOps Engineer"}).json()
    print(f"Role created: {role}")

    # 3. Create Employee
    resource = requests.post(f"{BASE_URL}/employees/", json={
        "name": "Max Mustermann",
        "type": "internal",
        "weekly_hours": 40.0,
        "employment_start": "2024-01-01",
        "role_id": role["id"],
        "team_id": team["id"]
    }).json()
    print(f"Resource created: {resource}")

    # 4. Create Project
    project = requests.post(f"{BASE_URL}/projects/", json={
        "name": "Project Alpha",
        "start_date": "2024-06-01",
        "end_date": "2024-12-31",
        "priority": 1,
        "status": "active"
    }).json()
    print(f"Project created: {project}")

    # 5. Create Staffing (Overlapping July 2024)
    staffing = requests.post(f"{BASE_URL}/staffings/", json={
        "project_id": project["id"],
        "resource_id": resource["id"],
        "start_date": "2024-07-01",
        "end_date": "2024-07-31",
        "capacity_fte": 0.5
    }).json()
    print(f"Staffing created: {staffing}")

    # 6. Analyze Heatmap for July 2024
    heatmap = requests.get(f"{BASE_URL}/analysis/heatmap/", params={"year": 2024, "month": 7}).json()
    print(f"Heatmap July 2024: {heatmap}")

if __name__ == "__main__":
    try:
        test_nvision()
    except Exception as e:
        print(f"Error: {e}. Make sure the server is running!")
