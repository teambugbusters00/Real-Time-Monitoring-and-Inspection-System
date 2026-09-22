from django.core.management.base import BaseCommand
from accounts.models import Division, NGO, User
from projects.models import Project, Beneficiary, PurposeItem


DEMO_PASSWORD = "pw"

NGOS = [
    ("NGO-JH-001", "Pragati Foundation", "Ranchi Division"),
    ("NGO-JH-002", "Jan Vikas Samiti", "Ranchi Division"),
    ("NGO-JH-003", "Navjeevan Trust", "Ranchi Division"),
    ("NGO-JH-004", "Samarpan Society", "Ranchi Division"),
    ("NGO-JH-005", "Kalyan Kendra", "Ranchi Division"),
    ("NGO-JH-006", "Gramin Seva", "Dhanbad Division"),
    ("NGO-JH-007", "Uday Society", "Dhanbad Division"),
    ("NGO-JH-008", "Asha Kiran", "Dhanbad Division"),
    ("NGO-JH-009", "Nirantar Vikas", "Dhanbad Division"),
    ("NGO-JH-010", "Sahyog Foundation", "Dhanbad Division"),
]

USERS = [
    ("rakesh_ranchi", "official", "Ranchi Division", None, "Rakesh", "Kumar"),
    ("insp1_ranchi", "inspector", "Ranchi Division", None, "Amit", "Singh"),
    ("insp2_ranchi", "inspector", "Ranchi Division", None, "Vikram", "Sharma"),
    ("insp3_ranchi", "inspector", "Ranchi Division", None, "Rajesh", "Yadav"),
    ("sanjay_dhanbad", "official", "Dhanbad Division", None, "Sanjay", "Verma"),
    ("insp1_dhanbad", "inspector", "Dhanbad Division", None, "Rahul", "Das"),
    ("insp2_dhanbad", "inspector", "Dhanbad Division", None, "Suresh", "Mahato"),
    ("insp3_dhanbad", "inspector", "Dhanbad Division", None, "Prakash", "Tiwari"),
    ("NGO-JH-001", "ngo", "Ranchi Division", "NGO-JH-001", "Pragati", "Foundation"),
    ("NGO-JH-002", "ngo", "Ranchi Division", "NGO-JH-002", "Jan Vikas", "Samiti"),
    ("NGO-JH-003", "ngo", "Ranchi Division", "NGO-JH-003", "Navjeevan", "Trust"),
    ("NGO-JH-004", "ngo", "Ranchi Division", "NGO-JH-004", "Samarpan", "Society"),
    ("NGO-JH-005", "ngo", "Ranchi Division", "NGO-JH-005", "Kalyan", "Kendra"),
    ("NGO-JH-006", "ngo", "Dhanbad Division", "NGO-JH-006", "Gramin", "Seva"),
    ("NGO-JH-007", "ngo", "Dhanbad Division", "NGO-JH-007", "Uday", "Society"),
    ("NGO-JH-008", "ngo", "Dhanbad Division", "NGO-JH-008", "Asha", "Kiran"),
    ("NGO-JH-009", "ngo", "Dhanbad Division", "NGO-JH-009", "Nirantar", "Vikas"),
    ("NGO-JH-010", "ngo", "Dhanbad Division", "NGO-JH-010", "Sahyog", "Foundation"),
]

PROJECTS = [
    ("Women Empowerment Skill Training", "NGO-JH-001", 362000, 334980, 6),
    ("Rural Solar Electrification", "NGO-JH-001", 446000, 178400, 7),
    ("Community Toilet Construction", "NGO-JH-001", 118000, 116892, 3),
    ("Orphanage Facility Upgrade", "NGO-JH-002", 93000, 86484, 6),
    ("Farmers Cooperative Grant", "NGO-JH-002", 376000, 373688, 5),
    ("Youth IT Literacy Center", "NGO-JH-002", 171000, 168065, 5),
    ("Clean Drinking Water Project", "NGO-JH-003", 83000, 81307, 3),
    ("Mobile Health Clinic Setup", "NGO-JH-003", 433000, 421635, 5),
    ("Organic Farming Workshop", "NGO-JH-004", 458000, 443618, 6),
    ("Senior Citizens Care Home", "NGO-JH-004", 71000, 28400, 4),
    ("Tribal Artisan Support", "NGO-JH-005", 475000, 430400, 3),
    ("Flood Relief Distribution", "NGO-JH-005", 311000, 293715, 6),
    ("Road Repair Initiative", "NGO-JH-006", 110000, 109408, 3),
    ("Primary School Renovation", "NGO-JH-006", 409000, 401101, 6),
    ("Disability Support Equipment", "NGO-JH-007", 370000, 350933, 4),
    ("Vocational Training Center", "NGO-JH-007", 480000, 449775, 4),
    ("Maternal Health Camp", "NGO-JH-008", 218000, 210688, 4),
    ("Tree Plantation Drive", "NGO-JH-008", 85000, 81964, 5),
    ("Village Pond Rejuvenation", "NGO-JH-009", 192000, 184790, 4),
    ("Self Help Group Microfinance", "NGO-JH-009", 331000, 322356, 5),
    ("Fishery Development Project", "NGO-JH-010", 156000, 150350, 6),
    ("Adult Literacy Program", "NGO-JH-010", 375000, 349168, 4),
]


class Command(BaseCommand):
    help = "Seeds idempotent NIRIKSHAN demo data for local or production environments."

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting NIRIKSHAN demo data seed...")

        divisions = {}
        for division_name in ("Ranchi Division", "Dhanbad Division"):
            divisions[division_name], _ = Division.objects.get_or_create(name=division_name)

        ngos = {}
        for registration_number, name, division_name in NGOS:
            ngo, _ = NGO.objects.update_or_create(
                registration_number=registration_number,
                defaults={"name": name, "division": divisions[division_name]},
            )
            ngos[registration_number] = ngo

        for username, role, division_name, ngo_registration, first_name, last_name in USERS:
            ngo = ngos.get(ngo_registration)
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(DEMO_PASSWORD)
            user.role = role
            user.division = divisions[division_name]
            user.ngo = ngo
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.save()

        for title, ngo_registration, allocated, claimed, beneficiary_count in PROJECTS:
            ngo = ngos[ngo_registration]
            project, _ = Project.objects.update_or_create(
                title=title,
                defaults={
                    "ngo": ngo,
                    "division": ngo.division,
                    "description": f"Demo monitoring project for {title}.",
                    "fund_allocated": allocated,
                    "fund_utilized_claimed": claimed,
                    "status": "active",
                },
            )

            for index in range(1, beneficiary_count + 1):
                Beneficiary.objects.get_or_create(
                    project=project,
                    name=f"Demo Beneficiary {index} - {title[:25]}",
                    defaults={"claimed": True},
                )

            PurposeItem.objects.get_or_create(
                project=project,
                description=f"Implementation activities for {title}",
                defaults={"claimed_status": "done"},
            )
            PurposeItem.objects.get_or_create(
                project=project,
                description=f"Beneficiary delivery and field verification for {title}",
                defaults={"claimed_status": "done"},
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete: {len(USERS)} users, {len(NGOS)} NGOs, {len(PROJECTS)} projects."
        ))
