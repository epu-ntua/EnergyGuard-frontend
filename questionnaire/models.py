from django.db import models


class Questionnaire(models.Model):
    title = models.CharField("Title", max_length=200)
    introduction_text = models.TextField("Introduction Text", blank=True,
                                         help_text="Text shown before starting the questionnaire.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI System Questionnaire"
        verbose_name_plural = "AI System Questionnaires"

    def __str__(self):
        return self.title


class SubQuestionnaire(models.Model):
    parent_questionnaire = models.ForeignKey(
        Questionnaire,
        related_name='sub_questionnaires',
        on_delete=models.CASCADE
    )
    title = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
        verbose_name = "Sub Questionnaire"
        verbose_name_plural = "Sub Questionnaires"

    def __str__(self):
        return f"{self.parent_questionnaire.title} -> {self.title}"


class Question(models.Model):
    STAGE_CHOICES = [
        (1, 'Scope'),
        (2, 'Your Legal Role'),
        (3, 'Exclusions from the scope of AI'),
        (4, 'Risk classification'),
        (5, 'High Risk'),
        (6, 'Limited Risk'),
        (7, 'Minimal Risk'),
    ]

    ANSWER_TYPES = [
        ('yes/no', 'Yes/No'),
        ('multiple', 'Multiple Choice'),
        ('summary', 'Summary/Result'),
        ('acknowledgment', 'Acknowledgment'),
    ]

    # We use CharField for the ID to accept values ​​like "1.1.1" or "4.1.result_prohibited" from JSON
    id = models.CharField(
        primary_key=True,
        max_length=100,
        help_text="The ID from questions_AI_System.json (e.g. 1.1.1)"
    )

    sub_questionnaire = models.ForeignKey(
        'SubQuestionnaire',
        on_delete=models.CASCADE,
        related_name='questions',
        null=True,
        blank=True
    )

    top_label = models.CharField(
        "Top Label Text",
        max_length=100,
        blank=True,
        null=True,
        help_text="Π.χ. 'Scope: Yes' ή 'Role: Provider'"
    )

    text = models.TextField("Question Text")

    help_text = models.TextField(
        "Help Text",
        blank=True,
        null=True,
        help_text="Additional information about the question"
    )

    result_text = models.TextField(
        "Result/Summary Text",
        blank=True,
        null=True,
        help_text="If the question is a summary type, the final result text is entered here."
    )

    order = models.IntegerField("Display Order", default=0)
    stage = models.IntegerField("Question Stage", choices=STAGE_CHOICES, default=1)
    answer_type = models.CharField(
        "Answer Type",
        max_length=50,
        choices=ANSWER_TYPES,
        default='yes/no'
    )

    is_multiple_choice = models.BooleanField("Allow Multiple Choices", default=False)

    class Meta:
        ordering = ['order']
        verbose_name = "Question"
        verbose_name_plural = "Questions"

    def __str__(self):
        sub_title = self.sub_questionnaire.title if self.sub_questionnaire else "No Sub"
        return f"[{self.id}] {self.text[:50]}..."

class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField("Choice Text", max_length=255)
    next_question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leading_choices'
    )

    is_out_of_scope = models.BooleanField(default=False, help_text="If selected, ends the test as Out of Scope")

    is_assessment_completed = models.BooleanField(
        default=False, 
        help_text="If selected, ends the test with the message Assessment Completed (Energy Guard)"
    )

    def __str__(self):
        return self.text