from datetime import datetime

from collections import defaultdict, OrderedDict

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, MONTHLY
from django.db.models.aggregates import Sum
from django.utils.translation import ugettext as _

from custom.icds_reports.const import LocationTypes
from custom.icds_reports.models import AggAwcMonthly
from custom.icds_reports.utils import apply_exclude


RED = '#de2d26'
ORANGE = '#fc9272'
BLUE = '#006fdf'
PINK = '#fee0d2'
GREY = '#9D9D9D'


def get_adolescent_girls_data_map(domain, config, loc_level, show_test=False):

    def get_data_for(filters):
        filters['month'] = datetime(*filters['month'])
        queryset = AggAwcMonthly.objects.filter(
            **filters
        ).values(
            '%s_name' % loc_level
        ).annotate(
            valid=Sum('cases_person_adolescent_girls_11_14') + Sum('cases_person_adolescent_girls_15_18'),
        )
        if not show_test:
            queryset = apply_exclude(domain, queryset)
        return queryset

    map_data = {}
    average = []
    for row in get_data_for(config):
        valid = row['valid']
        name = row['%s_name' % loc_level]

        average.append(valid)
        row_values = {
            'valid': valid or 0,
            'fillKey': 'Adolescent Girls'
        }

        map_data.update({name: row_values})

    fills = OrderedDict()
    fills.update({'Adolescent Girls': BLUE})
    fills.update({'defaultFill': GREY})

    return [
        {
            "slug": "adolescent_girls",
            "label": "",
            "fills": fills,
            "rightLegend": {
                "average": sum(average) / float(len(average) or 1),
                "average_format": 'number',
                "info": _((
                    "Total number of adolescent girls who are enrolled for ICDS services"
                )),
                "last_modify": datetime.utcnow().strftime("%d/%m/%Y"),
            },
            "data": map_data,
        }
    ]


def get_adolescent_girls_sector_data(domain, config, loc_level, show_test=False):
    group_by = ['%s_name' % loc_level]

    config['month'] = datetime(*config['month'])
    data = AggAwcMonthly.objects.filter(
        **config
    ).values(
        *group_by
    ).annotate(
        valid=Sum('cases_person_adolescent_girls_11_14') + Sum('cases_person_adolescent_girls_15_18'),
    ).order_by('%s_name' % loc_level)

    if not show_test:
        data = apply_exclude(domain, data)

    chart_data = {
        'blue': []
    }

    tooltips_data = defaultdict(lambda: {
        'valid': 0
    })

    for row in data:
        valid = row['valid']
        name = row['%s_name' % loc_level]

        row_values = {
            'valid': valid or 0,
        }
        for prop, value in row_values.iteritems():
            tooltips_data[name][prop] += value

        chart_data['blue'].append([
            name,
            valid
        ])

    return {
        "tooltips_data": tooltips_data,
        "format": "number",
        "info": _((
            "Total number of adolescent girls who are enrolled for ICDS services"
        )),
        "chart_data": [
            {
                "values": chart_data['blue'],
                "key": "Number Of Girls",
                "strokeWidth": 2,
                "classed": "dashed",
                "color": BLUE
            }
        ]
    }


def get_adolescent_girls_data_chart(domain, config, loc_level, show_test=False):
    month = datetime(*config['month'])
    three_before = datetime(*config['month']) - relativedelta(months=3)

    config['month__range'] = (three_before, month)
    del config['month']

    chart_data = AggAwcMonthly.objects.filter(
        **config
    ).values(
        'month', '%s_name' % loc_level
    ).annotate(
        valid=Sum('cases_person_adolescent_girls_11_14') + Sum('cases_person_adolescent_girls_15_18'),
    ).order_by('month')

    if not show_test:
        chart_data = apply_exclude(domain, chart_data)

    data = {
        'blue': OrderedDict()
    }

    dates = [dt for dt in rrule(MONTHLY, dtstart=three_before, until=month)]

    for date in dates:
        miliseconds = int(date.strftime("%s")) * 1000
        data['blue'][miliseconds] = {'y': 0, 'all': 0}

    best_worst = {}
    for row in chart_data:
        date = row['month']
        valid = (row['valid'] or 0)
        location = row['%s_name' % loc_level]

        if date.month == (month - relativedelta(months=1)).month:
            if location in best_worst:
                best_worst[location].append(valid)
            else:
                best_worst[location] = [valid]

        date_in_miliseconds = int(date.strftime("%s")) * 1000

        data['blue'][date_in_miliseconds]['y'] += valid

    top_locations = sorted(
        [dict(loc_name=key, value=sum(value) / len(value)) for key, value in best_worst.iteritems()],
        key=lambda x: x['value'],
        reverse=True
    )

    return {
        "chart_data": [
            {
                "values": [
                    {
                        'x': key,
                        'y': value['y'] / float(value['all'] or 1),
                        'all': value['all']
                    } for key, value in data['blue'].iteritems()
                ],
                "key": "Total number of adolescent girls who are enrolled for ICDS services",
                "strokeWidth": 2,
                "classed": "dashed",
                "color": BLUE
            }
        ],
        "all_locations": top_locations,
        "top_five": top_locations[:5],
        "bottom_five": top_locations[-5:],
        "location_type": loc_level.title() if loc_level != LocationTypes.SUPERVISOR else 'Sector'
    }
