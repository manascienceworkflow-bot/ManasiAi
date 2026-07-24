# Subscription CTA

Status: Active

Category: Subscription

CTA Type: Information Page

Priority: Subscription

Match Rule:

Display this CTA ONLY when:
- Category = Subscription
- Confidence = High

Do NOT display this CTA if:
- The conversation is primarily about a specific therapy.
- The conversation is primarily about a specific condition.
- The conversation is about practitioners.
- The conversation is about research articles or blogs.
- The conversation is about the Community Hub.
- The conversation is about Privacy Guidelines.
- The conversation is about the About page.
- The conversation is about the FAQ page.
- The user's intent is unrelated to subscriptions, membership, plans, or pricing.

Description:

Display this CTA when the user wants to learn about, compare, purchase, upgrade, renew, or manage a ManaScience subscription.

Trigger Examples:

## General Subscription Questions

- What is the ManaScience subscription?
- Tell me about your subscription.
- Explain the subscription.
- How does the subscription work?
- Do I need a subscription?
- Do you offer subscriptions?
- Is ManaScience free?
- Is ManaScience paid?
- Does ManaScience cost money?
- Do I have to pay?
- What plans do you offer?

## Pricing Questions

- How much does the subscription cost?
- What is the price?
- What are your pricing plans?
- Is there a monthly plan?
- Is there a yearly plan?
- What does it cost?
- Is there a free trial?
- Do you offer discounts?
- Are there family plans?
- Are there student plans?

## Membership Benefits

- What do I get with a subscription?
- What is included?
- What are the subscription benefits?
- Why should I subscribe?
- What features are included?
- What's included in the membership?
- What's the difference between free and paid?
- What can subscribers access?
- What premium features are available?

## Subscription Management

- How do I subscribe?
- How do I become a member?
- How do I sign up?
- How do I upgrade my plan?
- How do I renew my subscription?
- How do I cancel my subscription?
- Can I change my subscription?
- How do I manage my membership?
- How do I update my billing information?

## Access Questions

- Do I need a subscription to use Manasi?
- Do I need a subscription for Personalized Roadmap?
- Do I need a subscription for courses?
- What requires a subscription?
- Which features are free?
- Which features require payment?

## Platform Questions

- Can I use ManaScience without subscribing?
- Is there a free version?
- What happens if I don't subscribe?
- Can I upgrade later?
- Can I cancel anytime?
- Can I reactivate my subscription?

## Navigation Requests

- Subscription
- Subscription page
- Membership
- Membership page
- Pricing
- Pricing page
- Plans
- Plans page
- Upgrade
- Subscribe
- Open Subscription
- Show Subscription
- View Subscription Plans

Aliases:

- Subscription
- Membership
- Premium
- Premium Plan
- Paid Plan
- Pricing
- Plans
- Membership Plan
- Upgrade
- Subscription Plan

Related Topics:

- Membership
- Pricing
- Billing
- Payment
- Premium Features
- Courses
- Personalized Roadmap
- Account
- Access

Do NOT Trigger:

- Questions about specific therapies.
- Questions about specific conditions.
- Questions about practitioners.
- Questions about Community Hub.
- Questions about Privacy Guidelines.
- Questions about About ManaScience.
- Questions about FAQ.
- Questions about blogs or research.
- Questions requesting diagnosis.
- Questions requesting medical advice.
- Any query where another, more specific CTA should be displayed.

Fallback Rule:

If the Understanding Node cannot confidently determine that the user is asking about subscriptions, membership, plans, or pricing,

DO NOT display this CTA.

If another CTA is a better match, display that CTA instead.

Output Label:

Explore Subscription Plans

CTA:

https://manascience.webflow.io/subscription-landing-page
