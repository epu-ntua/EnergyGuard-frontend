from django.contrib import admin
from .models import Questionnaire, SubQuestionnaire, Question, Choice

# 1. Inline management for Choices within a Question
class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 1
    fk_name = "question"
    fields = ('text', 'next_question', 'is_out_of_scope', 'is_assessment_completed')

# 2. Inline management for Questions within a Sub-Questionnaire
class QuestionInline(admin.StackedInline):
    model = Question
    extra = 1
    show_change_link = True

# 3. Inline management for Sub-Questionnaires within the main Questionnaire
class SubQuestionnaireInline(admin.TabularInline):
    model = SubQuestionnaire
    extra = 1
    show_change_link = True

@admin.register(Questionnaire)
class QuestionnaireAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at')
    inlines = [SubQuestionnaireInline]

@admin.register(SubQuestionnaire)
class SubQuestionnaireAdmin(admin.ModelAdmin):
    list_display = ('title', 'parent_questionnaire', 'order')
    list_filter = ('parent_questionnaire',)
    inlines = [QuestionInline]

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'top_label', 'get_sub_questionnaire', 'order', 'stage')
    list_filter = ('sub_questionnaire__parent_questionnaire', 'sub_questionnaire')
    inlines = [ChoiceInline]

    def get_sub_questionnaire(self, obj):
        if obj.sub_questionnaire:
            return obj.sub_questionnaire.title
        return "No Sub-Questionnaire"

    get_sub_questionnaire.short_description = 'Sub Questionnaire'

@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    list_display = ('text', 'question', 'next_question')