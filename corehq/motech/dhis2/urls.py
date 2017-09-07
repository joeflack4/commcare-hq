from django.conf.urls import url
from corehq.motech.dhis2.view import (
    Dhis2ConnectionView,
    DataSetMapView,
    Dhis2LogListView,
    Dhis2LogDetailView,
    send_dhis2_data,
    get_data_sets,
    get_data_elements,
    get_cat_opt_combos,
)


urlpatterns = [
    url(r'^conn/$', Dhis2ConnectionView.as_view(), name=Dhis2ConnectionView.urlname),
    url(r'^map/$', DataSetMapView.as_view(), name=DataSetMapView.urlname),
    url(r'^map/datasets/$', get_data_sets, name='get_data_sets'),
    url(r'^map/datasets/(?P<data_set_id>\w+)/elems/$', get_data_elements, name='get_data_elements'),
    url(r'^map/datasets/(?P<data_set_id>\w+)/catopts/$', get_cat_opt_combos, name='get_cat_opt_combos'),
    url(r'^logs/$', Dhis2LogListView.as_view(), name=Dhis2LogListView.urlname),
    url(r'^logs/(?P<pk>\d+)/$', Dhis2LogDetailView.as_view(), name=Dhis2LogDetailView.urlname),
    url(r'^send/$', send_dhis2_data, name='send_dhis2_data'),
]
