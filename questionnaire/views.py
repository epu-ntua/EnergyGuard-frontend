from django.shortcuts import render, get_object_or_404, redirect
from .models import Questionnaire, SubQuestionnaire, Question, Choice

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

    context = {
        'question': question,
        'questionnaire': questionnaire,  # Defining variable to avoid NameError
        'stages': stages_list,
        'current_stage': question.stage,
        'stage_links': stage_links,
        'next_question_id': next_question_id,
        'result_text': request.session.pop('flash_result_text', None),
    }
    return render(request, 'questionnaire/question.html', context)

def submit_answer(request, question_id):
    current_question = get_object_or_404(Question, id=question_id)

    if request.method == 'POST':
        # 1. Handle TEXT type questions
        if current_question.answer_type == 'text':
            # For text, just get the first available choice defined during import
            choice = current_question.choices.first()

        # 2. Handle Radio/Checkbox types
        else:
            selected_ids = request.POST.getlist('choices')
            if not selected_ids:
                return redirect('questionnaire:detail', question_id=current_question.id)
            choice = get_object_or_404(Choice, id=selected_ids[0])

        request.session.modified = True

        # --- NAVIGATION ---
        next_q = choice.next_question

        if next_q:
            # If the next step is a .result page, store the text for the next view
            if ".result" in next_q.id:
                request.session['flash_result_text'] = next_q.result_text
            return redirect('questionnaire:detail', question_id=next_q.id)

    # Fallback if no next question is defined
    return redirect('questionnaire:assessment_completed')

def out_of_scope_view(request):
    return render(request, 'questionnaire/out_of_scope.html')

def assessment_completed_view(request):
    return render(request, 'questionnaire/assessment_completed.html')