function Choice (choice) {
    var self = this;
    self.value = ko.observable(choice);
}


function CustomDataField () {
    var self = this;
    self.slug = ko.observable();
    self.label = ko.observable();
    self.is_required = ko.observable();
    self.choices = ko.observableArray();
    self.multipleChoice = ko.observable();
    self.index_in_fixture = ko.observable();

    self.addChoice = function () {
        self.choices.unshift(new Choice());
    };

    self.removeChoice = function (choice) {
        self.choices.remove(choice);
    };

    self.init = function (field) {
        self.slug(field.slug);
        self.label(field.label);
        self.is_required(field.is_required);
        self.choices(field.choices.map(function (choice) {
            return new Choice(choice);
        }));
        self.multipleChoice(field.is_multiple_choice);
        self.index_in_fixture(field.index_in_fixture);
    };

    self.serialize = function () {
        var choices = [];
        var choicesToRemove = [];
        _.each(self.choices(), function (choice) {
            if (choice.value()) {
                choices.push(choice.value());
            } else {
                choicesToRemove.push(choice);
            }
        });
        _.each(choicesToRemove, function (choice) {
            self.removeChoice(choice);
        });

        return {
            'slug': self.slug(),
            'label': self.label(),
            'is_required': self.is_required(),
            'choices': choices,
            'is_multiple_choice': self.multipleChoice(),
            'index_in_fixture': self.index_in_fixture(),
        };
    };
}


function CustomDataFieldsModel () {
    var self = this;
    self.data_fields = ko.observableArray();
    self.purge_existing = ko.observable(false);
    // The data field that the "remove field modal" currently refers to.
    self.modalField = ko.observable();

    self.addField = function () {
        self.data_fields.push(new CustomDataField());
    };

    self.removeField = function (field) {
        self.data_fields.remove(field);
    };

    self.setModalField = function (field) {
        self.modalField(field);
    };

    self.confirmRemoveField = function () {
        // Remove the field that the "remove field modal" currently refers to.
        self.removeField(self.modalField());
    };

    self.init = function (initialFields) {
        _.each(initialFields, function (field) {
            custom_field = new CustomDataField();
            custom_field.init(field);
            self.data_fields.push(custom_field);
            custom_field.choices.subscribe(function() {
                $("#save-custom-fields").prop("disabled", false);
            });
        });
    };

    self.serialize = function () {
        var fields = [];
        var fieldsToRemove = [];
        _.each(self.data_fields(), function (field) {
            if(field.slug() || field.label()) {
                fields.push(field.serialize());
            } else {
                fieldsToRemove.push(field);
            }
        });

        _.each(fieldsToRemove, function (field) {
            self.removeField(field);
        });
        return fields;
    };

    self.submitFields = function (fieldsForm) {
        var customDataFieldsForm = $("<form>")
            .attr("method", "post")
            .attr("action", fieldsForm.action);


        $("<input type='hidden'>")
            .attr("name", 'csrfmiddlewaretoken')
            .attr("value", $("#csrfTokenContainer").val())
            .appendTo(customDataFieldsForm);

        $('<input type="hidden">')
            .attr('name', 'data_fields')
            .attr('value', JSON.stringify(self.serialize()))
            .appendTo(customDataFieldsForm);

        $('<input type="hidden">')
            .attr('name', 'purge_existing')
            .attr('value', self.purge_existing())
            .appendTo(customDataFieldsForm);
        customDataFieldsForm.appendTo("body");
        customDataFieldsForm.submit();
    };

}
