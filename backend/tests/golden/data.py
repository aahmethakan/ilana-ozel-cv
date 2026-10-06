from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenScenario:
    key: str
    candidate_name: str
    candidate_title: str
    education: str
    skills: tuple[str, ...]
    job_title: str
    company: str
    job_requirements: tuple[str, ...]
    forbidden: tuple[str, ...]


SCENARIOS = (
    GoldenScenario("mechanical", "Alex Morgan", "Installation Engineer", "Mechanical Engineering", ("PLC", "machine installation", "commissioning", "troubleshooting"), "Mechanical Engineer", "Apex Industrial Systems", ("PLC", "Siemens PLC", "SAP ERP", "Python", "commissioning"), ("Siemens", "SAP", "Python", "project management")),
    GoldenScenario("production", "Emily Carter", "Production Engineer", "Mechanical Engineering", ("production planning", "process improvement", "ERP", "Excel"), "Production Engineer", "Nova Manufacturing", ("production planning", "SAP", "advanced Excel", "quality systems"), ("SAP", "advanced Excel", "lean manufacturing")),
    GoldenScenario("software", "Daniel Lee", "Software Engineer", "Computer Science", ("Python", "REST APIs", "SQL", "Git", "automated testing"), "Backend Software Engineer", "CloudWorks", ("Python", "REST APIs", "SQL", "AWS", "Docker", "Kubernetes", "Java", "React"), ("AWS", "Docker", "Kubernetes", "Java", "React")),
    GoldenScenario("project", "Michael Brown", "Mechanical Project Engineer", "Mechanical Engineering", ("project coordination", "schedule tracking", "technical documentation", "supplier coordination"), "Project Manager", "Global Engineering Solutions", ("project coordination", "budget management", "team leadership", "portfolio management"), ("budget", "team leadership", "portfolio management")),
    GoldenScenario("graduate", "Sophia Wilson", "Graduate Engineer", "Mechanical Engineering", ("CAD", "technical drawing", "English"), "Junior Mechanical Engineer", "Engineering Labs", ("CAD", "technical drawing", "manufacturing", "commissioning", "2 years experience"), ("commissioning", "2 years", "manufacturing")),
)
