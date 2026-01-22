from django.shortcuts import render
from django.core.mail import send_mail
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

def home(request):
    return render(request, 'core/index.html', {})

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