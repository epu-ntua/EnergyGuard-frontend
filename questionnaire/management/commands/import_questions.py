import json
import os
from django.core.management.base import BaseCommand
from questionnaire.models import Questionnaire, SubQuestionnaire, Question, Choice


class Command(BaseCommand):
    help = 'Import data from questions.json with support for multiple choice answers'

    def handle(self, *args, **options):
        try:
            with open(os.path.join("questionnaire", "questions.json"), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR("File questions.json was not found."))
            return

        # Data Cleanup: Remove existing records before importing
        Choice.objects.all().delete()
        Question.objects.all().delete()
        SubQuestionnaire.objects.all().delete()
        Questionnaire.objects.all().delete()

        q_root_data = data['questionnaires'][0]

        # Create Questionnaire with static ID 2
        questionnaire = Questionnaire.objects.create(
            id=2,
            title=q_root_data['title'],
            introduction_text=q_root_data['description']
        )

        questions_map = {}

        # First Pass: Create Sections and Questions
        for section in q_root_data['sections']:
            sub = SubQuestionnaire.objects.create(
                parent_questionnaire=questionnaire,
                title=section['title'],
                description=section.get('description', ''),
                order=int(section['section_number'])
            )

            for q in section['questions']:
                question = Question.objects.create(
                    id=q['id'],
                    sub_questionnaire=sub,
                    text=q['question'],
                    help_text=q.get('help_text', ''),
                    result_text=q.get('result_text', ''),
                    answer_type=q.get('answer_type', 'yes/no'),
                    stage=int(section['section_number'])
                )
                questions_map[q['id']] = (question, q)

        # Second Pass: Map Choices (Answers & Options) and build relationships
        for q_id, (question_obj, q_data) in questions_map.items():
            question_obj.answer_type = q_data.get('answer_type', 'yes/no')
            question_obj.save()

            # Handle 'options' key (used for multiple choice)
            options_data = q_data.get('options', [])
            if isinstance(options_data, list):
                for opt in options_data:
                    # If option is an object {"text": "...", "next": "..."}
                    if isinstance(opt, dict):
                        txt = opt.get('text')
                        next_id = opt.get('next')
                        target = Question.objects.filter(id=next_id).first() if next_id else None
                        Choice.objects.get_or_create(question=question_obj, text=txt, next_question=target)
                    # If option is a simple string (legacy structure)
                    elif isinstance(opt, str):
                        Choice.objects.get_or_create(question=question_obj, text=opt, next_question=None)

            # Handle 'answers' key (typically used for yes/no branching)
            answers_dict = q_data.get('answers', {})
            if isinstance(answers_dict, dict):
                for text, info in answers_dict.items():
                    next_id = info.get('next')
                    target = Question.objects.filter(id=next_id).first() if next_id else None
                    Choice.objects.get_or_create(question=question_obj, text=text, next_question=target)

        self.stdout.write(self.style.SUCCESS(f'Import successful! Questionnaire ID: {questionnaire.id}'))