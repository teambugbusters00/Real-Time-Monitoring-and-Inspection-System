from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Division, NGO

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('DoSJE Info', {'fields': ('role', 'division', 'ngo', 'phone')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('DoSJE Info', {'fields': ('role', 'division', 'ngo', 'phone')}),
    )
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'division', 'is_staff')
    list_filter = ('role', 'division', 'is_staff', 'is_superuser', 'is_active')

@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')
    search_fields = ('name',)
    ordering = ('name',)


@admin.register(NGO)
class NGOAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'registration_number', 'division')
    list_filter = ('division',)
    search_fields = ('name', 'registration_number')
    ordering = ('name',)


admin.site.register(User, CustomUserAdmin)
