from django.core.management.base import BaseCommand
from accounts.models import Division, NGO, User
from projects.models import Project, Beneficiary, PurposeItem

class Command(BaseCommand):
    help = 'Seeds initial test data idempotently'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting data seed...")

        # 1. Divisions
        ranchi_div, _ = Division.objects.get_or_create(name="Ranchi Division")
        dhanbad_div, _ = Division.objects.get_or_create(name="Dhanbad Division")
        self.stdout.write("Divisions ensured.")

        # 2. NGOs
        asha_ngo, _ = NGO.objects.get_or_create(
            registration_number="NGO/RAN/2021/045",
            defaults={'name': "Asha Welfare Society", 'division': ranchi_div}
        )
        gyan_ngo, _ = NGO.objects.get_or_create(
            registration_number="NGO/DHN/2020/078",
            defaults={'name': "Gyan Jyoti Foundation", 'division': dhanbad_div}
        )
        self.stdout.write("NGOs ensured.")

        # 3. Users
        users_data = [
            ("rakesh_ranchi", "pw", "official", ranchi_div, None, "Rakesh", "Kumar"),
            ("insp1_ranchi", "pw", "inspector", ranchi_div, None, "Amit", "Singh"),
            ("insp2_ranchi", "pw", "inspector", ranchi_div, None, "Vikram", "Sharma"),
            ("insp3_ranchi", "pw", "inspector", ranchi_div, None, "Rajesh", "Yadav"),
            ("sanjay_dhanbad", "pw", "official", dhanbad_div, None, "Sanjay", "Verma"),
            ("insp1_dhanbad", "pw", "inspector", dhanbad_div, None, "Rahul", "Das"),
            ("insp2_dhanbad", "pw", "inspector", dhanbad_div, None, "Suresh", "Mahato"),
            ("insp3_dhanbad", "pw", "inspector", dhanbad_div, None, "Prakash", "Tiwari"),
            ("NGO-JH-001", "pw", "ngo", ranchi_div, None, "Pragati", "Foundation"),
            ("NGO-JH-002", "pw", "ngo", ranchi_div, None, "Jan Vikas", "Samiti"),
            ("NGO-JH-003", "pw", "ngo", ranchi_div, None, "Navjeevan", "Trust"),
            ("NGO-JH-004", "pw", "ngo", ranchi_div, None, "Samarpan", "Society"),
            ("NGO-JH-005", "pw", "ngo", ranchi_div, None, "Kalyan", "Kendra"),
            ("NGO-JH-006", "pw", "ngo", dhanbad_div, None, "Gramin", "Seva"),
            ("NGO-JH-007", "pw", "ngo", dhanbad_div, None, "Uday", "Society"),
            ("NGO-JH-008", "pw", "ngo", dhanbad_div, None, "Asha", "Kiran"),
            ("NGO-JH-009", "pw", "ngo", dhanbad_div, None, "Nirantar", "Vikas"),
            ("NGO-JH-010", "pw", "ngo", dhanbad_div, None, "Sahyog", "Foundation"),
        ]

        ngo_by_username = {
            "NGO-JH-001": ("Pragati Foundation", "NGO-JH-001", ranchi_div),
            "NGO-JH-002": ("Jan Vikas Samiti", "NGO-JH-002", ranchi_div),
            "NGO-JH-003": ("Navjeevan Trust", "NGO-JH-003", ranchi_div),
            "NGO-JH-004": ("Samarpan Society", "NGO-JH-004", ranchi_div),
            "NGO-JH-005": ("Kalyan Kendra", "NGO-JH-005", ranchi_div),
            "NGO-JH-006": ("Gramin Seva", "NGO-JH-006", dhanbad_div),
            "NGO-JH-007": ("Uday Society", "NGO-JH-007", dhanbad_div),
            "NGO-JH-008": ("Asha Kiran", "NGO-JH-008", dhanbad_div),
            "NGO-JH-009": ("Nirantar Vikas", "NGO-JH-009", dhanbad_div),
            "NGO-JH-010": ("Sahyog Foundation", "NGO-JH-010", dhanbad_div),
        }
        ngo_users = {}
        for username, (ngo_name, registration_number, division) in ngo_by_username.items():
            ngo, _ = NGO.objects.update_or_create(
                registration_number=registration_number,
                defaults={"name": ngo_name, "division": division},
            )
            ngo_users[username] = ngo

        for username, password, role, div, ngo, first_name, last_name in users_data:
            if role == "ngo":
                ngo = ngo_users[username]
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.role = role
            user.division = div
            user.ngo = ngo
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.save()
            user, created = User.objects.get_or_create(username=username)
            if created or user.role != role:
                user.set_password(password)
                user.role = role
                user.division = div
                user.ngo = ngo
                user.save()
        self.stdout.write("Users ensured.")

        # 4. Projects
        comp_lab, _ = Project.objects.get_or_create(
            title="Computer Lab Project",
            defaults={
                'ngo': asha_ngo,
                'division': ranchi_div,
                'description': "Setting up computers in Ranchi schools.",
                'fund_allocated': 5000.00,
                'fund_utilized_claimed': 5000.00
            }
        )
        # Ensure it belongs to the right division/ngo just in case it existed before
        comp_lab.ngo = asha_ngo
        comp_lab.division = ranchi_div
        comp_lab.fund_allocated = 5000.00
        comp_lab.fund_utilized_claimed = 5000.00
        comp_lab.save()

        solar_pump, _ = Project.objects.get_or_create(
            title="Solar Water Pump Project",
            defaults={
                'ngo': gyan_ngo,
                'division': dhanbad_div,
                'description': "Installing solar water pumps in Dhanbad.",
                'fund_allocated': 8000.00,
                'fund_utilized_claimed': 7500.00
            }
        )
        self.stdout.write("Projects ensured.")

        # 5. Beneficiaries
        comp_bens = ["Ramesh Oraon", "Sunita Devi", "Anil Kumar", "Priya Kumari"]
        for b_name in comp_bens:
            Beneficiary.objects.get_or_create(project=comp_lab, name=b_name, defaults={'claimed': True})
            
        solar_bens = ["Mohan Mahto", "Kavita Singh"]
        for b_name in solar_bens:
            Beneficiary.objects.get_or_create(project=solar_pump, name=b_name, defaults={'claimed': True})
        self.stdout.write("Beneficiaries ensured.")

        # 6. Purpose Items
        comp_purposes = [
            ("Fund for 10 computers to be installed in village school", "done"),
            ("Internet connectivity setup for the lab", "done")
        ]
        for p_desc, p_status in comp_purposes:
            PurposeItem.objects.get_or_create(
                project=comp_lab, 
                description=p_desc, 
                defaults={'claimed_status': p_status}
            )

        solar_purposes = [
            ("Installation of 2 solar-powered water pumps", "done"),
            ("Training for local operators", "partial")
        ]
        for p_desc, p_status in solar_purposes:
            PurposeItem.objects.get_or_create(
                project=solar_pump, 
                description=p_desc, 
                defaults={'claimed_status': p_status}
            )
        self.stdout.write("PurposeItems ensured.")

        self.stdout.write(self.style.SUCCESS("Successfully seeded all data!"))
