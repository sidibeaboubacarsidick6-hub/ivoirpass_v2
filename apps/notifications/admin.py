from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import AdminNotification


@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    list_display = ('type', 'title', 'is_read', 'created_at')
    list_filter = ('type', 'is_read')
    readonly_fields = ('type', 'title', 'message', 'reference', 'created_at')
    ordering = ('-created_at',)

    actions = ['mark_read']

    @admin.action(description="✅ Marquer comme lues")
    def mark_read(self, request, queryset):
        queryset.update(is_read=True)
        self.message_user(request, "Notifications marquées comme lues.")
