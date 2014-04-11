from decimal import Decimal
import stripe
from django.conf import settings
from corehq.apps.accounting.exceptions import PaymentHandlerError
from corehq.apps.accounting.models import PaymentMethodType, PaymentRecord, CreditLine
from dimagi.utils.decorators.memoized import memoized

stripe.api_key = settings.STRIPE_PRIVATE_KEY


class PaymentHandler(object):

    def __init__(self, payment_method, invoice):
        self.payment_method = payment_method
        self.invoice = invoice

    def process_request(self, request):
        """Process the HTTPRequest used to make this payment

        returns a dict to be used as the json response for the request.
        """
        raise NotImplementedError("you must implement process_request")

    @classmethod
    def create(cls, payment_method, invoice):
        handler_class = {
            PaymentMethodType.STRIPE: StripePaymentHandler,
        }.get(payment_method.method_type)
        if handler_class is None:
            raise PaymentHandlerError("Could not find an appropriate handler")
        return handler_class(payment_method, invoice)


class StripePaymentHandler(PaymentHandler):

    @property
    @memoized
    def stripe_customer(self):
        customer = None
        if self.payment_method.customer_id is not None:
            try:
                customer = stripe.Customer.retrieve(self.payment_method.customer_id)
            except stripe.InvalidRequestError:
                pass
        if customer is None:
            customer = stripe.Customer.create(
                description="Account Admin %(web_user)s for %(domain)s, "
                            "Account %(account_name)s" % {
                    'web_user': self.payment_method.billing_admin.web_user,
                    'domain': self.payment_method.billing_admin.domain,
                    'account_name': self.payment_method.account.name,
                },
                email=self.payment_method.billing_admin.web_user,
            )
        self.payment_method.customer_id = customer.id
        self.payment_method.save()
        return customer

    def get_charge_amount(self, request):
        if request.POST['paymentAmount'] == 'full':
            return self.invoice.balance.quantize(Decimal(10) ** -2)
        return Decimal(request.POST['customPaymentAmount'])

    def get_amount_in_cents(self, amount):
        amt_cents = amount * Decimal('100')
        return int(amt_cents.quantize(Decimal(10)))

    def process_request(self, request):
        card_token = request.POST.get('stripeToken')
        amount = self.get_charge_amount(request)
        charge = stripe.Charge.create(
            card=card_token,
            amount=self.get_amount_in_cents(amount),
            currency=settings.DEFAULT_CURRENCY,
        )
        payment_record = PaymentRecord.create_record(self.payment_method,
                                                     charge.id)
        # record the credit to the account
        CreditLine.add_credit(
            amount, account=self.invoice.subscription.account,
            payment_record=payment_record,
        )
        CreditLine.add_credit(
            amount * Decimal('-1.0'),
            account=self.invoice.subscription.account,
            invoice=self.invoice,
        )
        self.invoice.update_balance()
        self.invoice.save()

        # todo handle stripe api errors
        return {}
