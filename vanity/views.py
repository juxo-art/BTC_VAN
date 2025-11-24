from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .forms import VanityForm
from .utils import generate_matching, stop_generation
from .models import VanityAddress


def index(request):
    form = VanityForm()
    return render(request, "vanity/index.html", {"form": form})


@csrf_exempt
def stop_generation_view(request):
    """
    When user clicks STOP, this is triggered via AJAX.
    """
    stop_generation()  # calls utils.py stop function
    return JsonResponse({"stopped": True})


@csrf_exempt
def generate_address(request):
    """
    BTC vanity address generator API endpoint.
    Uses multiprocessing + real stop function.
    """
    # Always reset stop before starting
    stop_generation()

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=400)

    form = VanityForm(request.POST)
    if not form.is_valid():
        return JsonResponse({
            "error": "Invalid input",
            "errors": form.errors
        }, status=400)

    prefix = (form.cleaned_data["prefix"] or "").strip()
    suffix = (form.cleaned_data["suffix"] or "").strip()

    # BTC addresses MUST start with "1"
    #if prefix and not prefix.startswith("1"):
       # return JsonResponse({
            #"error": "BTC addresses always start with '1'. Update your prefix."
        #}, status=400)

    # If user didn't give prefix → generator will use full random "1"
    final_prefix = prefix if prefix else "1"

    # CALL utils.py  (returns dict!)
    result = generate_matching(
        prefix=final_prefix,
        suffix=suffix,
        max_tries=500000
    )

    # SAFETY; if utils returns None (your utils.py has this bug)
    if result is None:
        return JsonResponse({
            "error": "Internal generator error. (utils returned None)"
        },
        status= 500)

    # If user clicked STOP
    if result.get("stopped"):
        return JsonResponse({
            "stopped": True,
            "tries": result.get("tries"),
            "time": result.get("time")
        })

    # If no result found
    if result.get("error"):
        return JsonResponse({
            "error": result["message"],
            "tries": result.get("tries")
        }, status=400)

    # Save to database
    VanityAddress.objects.create(
        address=result["address"],
        private_key=result["private_key"],
        prefix=prefix,
        suffix=suffix
    )

    # Response
    return JsonResponse({
        "address": result["address"],
        "private_key": result["private_key"],
        "tries": result["tries"],
        "time": result["time"]
    })