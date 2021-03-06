from custom.fri.reports.reports import (
    MessageBankReport, MessageReport, PHEDashboardReport,
    SurveyResponsesReport,
)

CUSTOM_REPORTS = (
    ('FRI', (
        PHEDashboardReport,
        SurveyResponsesReport,
        MessageBankReport,
        MessageReport,
    )),
)
