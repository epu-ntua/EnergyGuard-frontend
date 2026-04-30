import json
from django.utils import timezone
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from .models import Questionnaire, SubQuestionnaire, Question, Choice, UserAnswer, Assessment

def start_questionnaire(request, questionnaire_id):
    questionnaire = get_object_or_404(Questionnaire, id=questionnaire_id)

    # Clear user roles from session when the test starts
    request.session['user_roles'] = []
    request.session.modified = True

    first_question = Question.objects.filter(
        sub_questionnaire__parent_questionnaire=questionnaire
    ).order_by('id').first()

    return render(request, 'questionnaire/intro.html', {
        'questionnaire': questionnaire,
        'first_question': first_question
    })

def question_detail(request, question_id):
    question = get_object_or_404(Question, id=question_id)

    # AUTOMATIC REDIRECT FOR ACKNOWLEDGMENT TYPES
    if question.answer_type == 'acknowledgment':
        # Get the first available choice
        first_choice = question.choices.first()
        if first_choice and first_choice.next_question:
            # If result text exists, store it in the session
            if question.result_text:
                request.session['flash_result_text'] = question.result_text

            # Redirect to the next question without rendering the current one
            return redirect('questionnaire:detail', question_id=first_choice.next_question.id)

    sub_q = question.sub_questionnaire
    questionnaire = sub_q.parent_questionnaire if sub_q else Questionnaire.objects.first()

    # Stepper logic
    stages_list = [stage[1] for stage in Question.STAGE_CHOICES]
    stage_links = {}
    if questionnaire:
        for stage_num, stage_name in Question.STAGE_CHOICES:
            first_q_in_stage = Question.objects.filter(
                sub_questionnaire__parent_questionnaire=questionnaire,
                stage=stage_num
            ).order_by('id').first()
            if first_q_in_stage:
                stage_links[stage_num] = first_q_in_stage.id

    # Finding the next ID specifically for .result pages (Continue button)
    next_question_id = None
    first_choice = question.choices.first()
    if first_choice and first_choice.next_question:
        next_question_id = first_choice.next_question.id

    category = request.session.get('final_risk_display', None)

    user_roles = request.session.get('user_roles', [])
    logic_conditions = request.session.get('logic_conditions', {})

    context = {
        'question': question,
        'questionnaire': questionnaire,  # Defining variable to avoid NameError
        'stages': stages_list,
        'current_stage': question.stage,
        'stage_links': stage_links,
        'next_question_id': next_question_id,
        'category': category,
        'result_text': request.session.pop('flash_result_text', None),
        'user_roles': user_roles,
        'logic_conditions': logic_conditions,
    }
    return render(request, 'questionnaire/question.html', context)

def submit_answer(request, question_id):
    current_question = get_object_or_404(Question, id=question_id)

    # Ensure a session exists and retrieve the key
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    if request.method == 'POST':
        selected_ids = request.POST.getlist('choices')

        # Validation: stay on current page if no answer is selected
        if not selected_ids:
            return redirect('questionnaire:detail', question_id=current_question.id)

        # 1. Save progress to UserAnswer (Intermediate storage for session)
        user_answer, created = UserAnswer.objects.get_or_create(
            session_key=session_key,
            question=current_question
        )
        user_answer.selected_choices.set(selected_ids)
        user_answer.save()

        choice = get_object_or_404(Choice, id=selected_ids[0])
        next_q = choice.next_question

        # --- Dynamic Risk Identification ---

        # 1. Control for Prohibited Practices (Unacceptable Risk)
        if next_q and "4.1.result_prohibited" in next_q.id:
            request.session['ai_risk_level'] = "Unacceptable Risk (Prohibited)"
            request.session['is_high_risk'] = False

        # 2. Temporary Marking of Potential High Risk (Before Exemptions)
        elif next_q and "4.2.result_highrisk" in next_q.id:
            # Εδώ το σύστημα ΔΕΝ θεωρείται ακόμα High Risk, αλλά "Potential High Risk"
            request.session['ai_risk_level'] = "Potential High Risk"
            request.session['is_high_risk'] = False  # Παραμένει False μέχρι την επιβεβαίωση

        # 3. CONFIRMATION of High Risk (After Section 4.3, if there was no exception)
        elif next_q and "4.result_confirmed_highrisk" in next_q.id:
            request.session['ai_risk_level'] = "High Risk"
            request.session['is_high_risk'] = True

        # 4. APPLICATION OF EXCEPTION (Conversion to Limited Risk)
        # If the user is led to 4.3.result_exception, the risk is downgraded
        elif next_q and "4.3.result_exception" in next_q.id:
            request.session['ai_risk_level'] = "Limited Risk"
            request.session['is_high_risk'] = False

        # 5. Check for Non-High Risk from the beginning (Section 4.2 -> No)
        elif next_q and "4.2.result_not_highrisk" in next_q.id:
            request.session['ai_risk_level'] = "Limited/Minimal Risk"
            request.session['is_high_risk'] = False

        # 6. Transparency (Limited Risk - Section 7)
        elif next_q and "7.result" in next_q.id:
            # Αν δεν έχουμε ήδη "κλειδώσει" σε High Risk, τότε είναι Limited
            if request.session.get('ai_risk_level') != "High Risk":
                request.session['ai_risk_level'] = "Limited Risk"
                request.session['is_high_risk'] = False

        # 7. Out of Scope
        if next_q and ("result_exempt" in next_q.id or next_q.id == "1.3"):
            request.session['ai_risk_level'] = "Exempt (Out of Scope)"
            request.session['is_high_risk'] = False

        # 2. Checklist vs Radio logic for navigation
        if current_question.answer_type == 'checklist':
            # Exclude technical markers to calculate real selection coverage
            all_choice_ids = set(current_question.choices.exclude(
                text__in=['all_checked', 'some_checked', 'none_checked']
            ).values_list('id', flat=True))

            selected_ids_set = set(map(int, selected_ids))

            if selected_ids_set == all_choice_ids:
                choice = current_question.choices.filter(text='all_checked').first()
            elif len(selected_ids_set) > 0:
                choice = current_question.choices.filter(text='some_checked').first()
            else:
                choice = current_question.choices.filter(text='none_checked').first()

            # Fallback to first selected choice if logic above doesn't yield a result
            if not choice:
                choice = get_object_or_404(Choice, id=selected_ids[0])
        else:
            # Standard single choice logic
            choice = get_object_or_404(Choice, id=selected_ids[0])

        # 3. Classification Logic (Risk Level & Exemptions)

        # # High Risk detection based on specific question IDs
        # high_risk_ids = ['1.1.4', '1.1.5', '2.1.1']
        # if current_question.id in high_risk_ids and choice.text.lower() == "yes":
        #     request.session['ai_risk_level'] = "High Risk"

        # Determine next navigation step
        next_q = choice.next_question if choice else None

        # Specific Logic for Scope & Exemptions Analysis (Section 3)
        if next_q and next_q.id == "3.1.result_exempt":
            request.session['ai_risk_level'] = "Exempt (Out of Scope)"

        request.session.modified = True

        # 4. Final Assessment Snapshot (Triggered on any .result page)
        if next_q and ".result" in next_q.id:
            # Gather all session answers to freeze them in the Assessment record
            all_user_answers = UserAnswer.objects.filter(session_key=session_key).select_related('question')
            responses_data = []
            for ua in all_user_answers:
                responses_data.append({
                    "question_id": ua.question.id,
                    "question_text": ua.question.text,
                    "answers": [c.text for c in ua.selected_choices.all()]
                })

            # Save the final report data
            Assessment.objects.update_or_create(
                session_key=session_key,
                defaults={
                    "final_classification": request.session.get('ai_risk_level', "Minimal Risk"),
                    "full_responses_dump": responses_data
                }
            )

        # 5. Redirect Handling & Role Identification
        if next_q:
            user_roles = request.session.get('user_roles', [])

            if next_q.id == "2.1.result_provider" or next_q.id == "2.3.result_provider" or next_q.id == "2.4.result_provider":
                if "provider" not in user_roles:
                    user_roles.append("provider")

            if next_q.id == "2.2.result_deployer":
                if "deployer" not in user_roles:
                    user_roles.append("deployer")

            request.session['user_roles'] = user_roles
            request.session.modified = True

            # Ορισμός των conditions για την πλοήγηση που χρησιμοποιεί το JSON
            is_provider = "provider" in user_roles
            is_deployer = "deployer" in user_roles

            # Ειδική λογική για τη σελίδα αποτελεσμάτων (π.χ. 4.result_confirmed_highrisk)
            # Εδώ προετοιμάζουμε τις μεταβλητές που περιμένει το template ή η επόμενη ερώτηση
            context_conditions = {
                'if_provider_role': is_provider and not is_deployer,
                'if_deployer_role_only': is_deployer and not is_provider,
                'if_both_roles': is_provider and is_deployer,
                'if_provider': is_provider,
                'if_deployer': is_deployer,
            }
            # Αποθήκευση στο session για να είναι διαθέσιμα στο επόμενο request
            request.session['logic_conditions'] = context_conditions



            # Special logic for the very last result page (summary)
            if next_q.id == "8.result":
                request.session['final_risk_display'] = request.session.get('ai_risk_level', "Minimal Risk")

            if ".result" in next_q.id:
                request.session['flash_result_text'] = next_q.result_text

            return redirect('questionnaire:detail', question_id=next_q.id)

    # Fallback: Redirect to the start of the questionnaire
    parent_id = current_question.sub_questionnaire.parent_questionnaire.id
    return redirect('questionnaire:start', questionnaire_id=parent_id)

def out_of_scope_view(request):
    return render(request, 'questionnaire/out_of_scope.html')

def assessment_completed_view(request):
    return render(request, 'questionnaire/assessment_completed.html')

def download_assessment_json(request):
    session_key = request.session.session_key
    # Get the latest assessment for this session
    assessment = Assessment.objects.filter(session_key=session_key).last()

    if not assessment:
        return HttpResponse("No completed assessment found.", status=404)

    export_data = {
        "report_id": assessment.id,
        "classification": assessment.final_classification,
        "completion_date": assessment.created_at.isoformat(),
        "responses": assessment.full_responses_dump
    }

    response = HttpResponse(
        json.dumps(export_data, indent=4, ensure_ascii=False),
        content_type='application/json'
    )
    response['Content-Disposition'] = f'attachment; filename="AI_Report_{assessment.id}.json"'
    return response