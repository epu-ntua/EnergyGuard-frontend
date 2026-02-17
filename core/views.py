from django.shortcuts import render
from django.core.mail import send_mail
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from formtools.wizard.views import SessionWizardView
from django.core.files.storage import FileSystemStorage
from django.shortcuts import redirect
from django.db.models import Count
import os
import tempfile
from django.contrib.auth.decorators import login_required
from datasets.models import Dataset

# Create your views here.

def home(request):
    return render(request, 'core/landing-public.html', {})

def error_does_not_exist(request, error=None):
    return render(request, 'core/error-does-not-exist.html', {"error": error})

def collaboration_hub(request):
    return render(request, 'core/collaboration-hub.html', {"active_navbar_page": "collaboration_hub", "show_sidebar": True})

def documentation(request):
    return render(request, 'core/documentation.html', {"active_navbar_page": "documentation", "show_sidebar": True})

@require_http_methods(["POST"])
def contact_form(request):
    # Handle contact form submissions and send email
    try:
        name = request.POST.get('name', '')
        email = request.POST.get('email', '')
        message = request.POST.get('message', '')
        
        # Validate inputs
        if not name or not email or not message:
            return JsonResponse({'success': False, 'message': 'All fields are required'}, status=400)
        
        # Prepare email
        subject = f"New Contact Form Submission from {name}"
        email_message = f"""
        New message from EnergyGuard Contact Form:

        Name: {name}
        Email: {email}
        Message:
        {message}
        """
        
        # Send email
        send_mail(
            subject,
            email_message,
            settings.DEFAULT_FROM_EMAIL,
            ['no-reply@energy-guard.eu'],
            fail_silently=False,
        )
        
        return JsonResponse({'success': True, 'message': 'Message sent successfully!'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error sending message: {str(e)}'}, status=500)
    
class BaseWizardView(SessionWizardView):
    # Necessary to handle ImageField or FileField in forms
    # Keep wizard step uploads out of MEDIA_ROOT (these are temporary files).
    file_storage = FileSystemStorage(
        location=os.path.join(tempfile.gettempdir(), 'energyguard_wizard_uploads_temp')
    )
    template_names = {}
    step_metadata = {}

    def dispatch(self, request, *args, **kwargs):
        # Check if user is authenticated
        if not request.user.is_authenticated:
            return redirect('login')
        return super().dispatch(request, *args, **kwargs)

    def get_template_names(self):
        # Change default template names according to the current step
        return [self.template_names[self.steps.current]]

    def get_context_data(self, form, **kwargs):
        context = super().get_context_data(form=form, **kwargs)
        steps = []
        for step_name in self.steps.all:
            meta = self.step_metadata.get(step_name, {})
            steps.append(
                {
                    "name": step_name,
                    "title": meta.get("title", step_name.replace("_", " ").title()),
                    "icon": meta.get("icon", "fa-user"),
                }
            )
        context["wizard_steps"] = steps
        return context

@login_required
def dashboard(request):

    counts_by_label = {
        row["label"]: row["total"]
        for row in Dataset.objects.filter(publisher__isnull=True).values("label").annotate(total=Count("id"))
    }

    chart_data = [
        {
            "category": label_display,
            "value": counts_by_label.get(label_value, 0),
        }
        for label_value, label_display in Dataset.Label.choices
    ]
    chart_data.sort(key=lambda item: item["value"], reverse=True)

    return render(request, 'core/dashboard.html', {"active_navbar_page": "dashboard", "show_sidebar": True, "chart_data": chart_data})