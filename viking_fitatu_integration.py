import requests
import uuid
import logging
import config

from config import (VIKING_COOKIE, VIKING_ORDER_ID, FITATU_SECRET, FITATU_AUTHORIZATION, FITATU_USER_ID)
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BRAND = "Viking"
TARGET_DATES = getattr(config, "TARGET_DATES", None)
TARGET_DATE_RANGE = getattr(config, "TARGET_DATE_RANGE", None)
MEAL_MAPPING = getattr(config, 'MEAL_MAPPING', {
    "Śniadanie": "breakfast",
    "II śniadanie": "second_breakfast",
    "Obiad": "dinner",
    "Podwieczorek": "snack",
    "Kolacja": "supper"
})

class APIConfig:
    """Stores API configurations for Viking and Fitatu."""
    VIKING_HEADERS = {"Cookie": VIKING_COOKIE}
    FITATU_HEADERS = {
        "Api-Key": "FITATU-MOBILE-APP",
        "Api-Secret": FITATU_SECRET,
        "Authorization": FITATU_AUTHORIZATION,
        "Content-Type": "application/json"
    }

    VIKING_ORDER_LIST = "https://panel.kuchniavikinga.pl/api/company/customer/order/all"
    VIKING_ORDER_URL = "https://panel.kuchniavikinga.pl/api/company/customer/order/{id}"
    VIKING_DATE_DETAILS_URL = "https://panel.kuchniavikinga.pl/api/company/general/menus/delivery/{id}/new"

    FITATU_BASE_URL = "https://pl-pl.fitatu.com/api"
    FITATU_CREATE_PRODUCT_URL = f"{FITATU_BASE_URL}/products"
    FITATU_DELETE_PRODUCT_URL = f"{FITATU_BASE_URL}/products/{{product_id}}"
    FITATU_SEARCH_PRODUCT_URL = f"{FITATU_BASE_URL}/search/food/user/{FITATU_USER_ID}?date={{date}}&phrase={{phrase}}&page=1&limit=50"
    FITATU_DIET_PLAN_URL = f"{FITATU_BASE_URL}/diet-plan/{FITATU_USER_ID}/days"
    FITATU_GET_DIET_PLAN_URL = f"{FITATU_BASE_URL}/diet-and-activity-plan/{FITATU_USER_ID}/day/{{date}}"


class BaseClient:
    """Base class for API clients with request handling."""

    @staticmethod
    def get(url: str, headers: dict) -> dict | None:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        logging.error(f"Error fetching data from {url}: {response.status_code} - {response.text}")
        return None

    @staticmethod
    def post(url: str, data: dict, headers: dict) -> dict | None:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        if response.status_code in (200, 201, 202):
            response_data = response.json()
            if isinstance(response_data, list):
                for item in response_data:
                    if "errorMessage" in item and item["errorMessage"]:
                        logging.error(f"Error response from {url}: {item['errorMessage']}")
                        return None
            return response_data
        logging.error(f"Error posting data to {url}: {response.status_code} - {response.text}")
        return None

    @staticmethod
    def delete(url: str, headers: dict) -> bool:
        response = requests.delete(url, headers=headers, timeout=30)
        if response.status_code in (200, 204):
            return True
        logging.error(f"Error deleting from {url}: {response.status_code} - {response.text}")
        return False


class VikingClient(BaseClient):
    """Handles API interactions with Viking."""

    @staticmethod
    def get(url: str) -> dict | None:
        return BaseClient.get(url, APIConfig.VIKING_HEADERS)


class FitatuClient(BaseClient):
    """Handles API interactions with Fitatu."""

    @staticmethod
    def get(url: str) -> dict | None:
        return BaseClient.get(url, APIConfig.FITATU_HEADERS)

    @staticmethod
    def post(url: str, data: dict) -> dict | None:
        return BaseClient.post(url, data, APIConfig.FITATU_HEADERS)

    @staticmethod
    def delete(url: str) -> bool:
        return BaseClient.delete(url, APIConfig.FITATU_HEADERS)


def select_dates() -> list[str]:
    """Selects dates based on provided config variables."""
    if TARGET_DATES and TARGET_DATE_RANGE:
        raise ValueError("Only one of TARGET_DATES or TARGET_DATE_RANGE should be provided.")

    if isinstance(TARGET_DATES, list):
        logging.info(f"Selected dates: {TARGET_DATES}")
        return TARGET_DATES

    if isinstance(TARGET_DATE_RANGE, tuple) and len(TARGET_DATE_RANGE) == 2:
        start_date, end_date = map(lambda d: datetime.strptime(d, "%Y-%m-%d"), TARGET_DATE_RANGE)
        selected_dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((end_date - start_date).days + 1)]
        logging.info(f"Selected date range: {TARGET_DATE_RANGE}")
        return selected_dates

    logging.error("No valid dates provided. Skipping...")
    return []


def search_all_products(name: str, date: str) -> list:
    """Search for all products by name and date in Fitatu. Returns list of matching products."""
    products = FitatuClient.get(APIConfig.FITATU_SEARCH_PRODUCT_URL.format(date=date, phrase=name))
    
    if products:
        return [p for p in products if p.get("name") == name and p.get("brand") == BRAND]
    return []


def create_product(product_data: dict) -> str | None:
    """Creates a new product in Fitatu."""
    response = FitatuClient.post(APIConfig.FITATU_CREATE_PRODUCT_URL, product_data)
    return response.get("id") if response else None


def delete_product(product_id: str) -> bool:
    """Deletes a product from Fitatu."""
    return FitatuClient.delete(APIConfig.FITATU_DELETE_PRODUCT_URL.format(product_id=product_id))


def get_existing_diet_plan(date: str) -> dict:
    """Retrieves existing diet plan for the given date."""
    response = FitatuClient.get(APIConfig.FITATU_GET_DIET_PLAN_URL.format(date=date))
    return {
        meal_key: [item for item in meal_data.get("items", []) if item.get("brand") == BRAND]
        for meal_key, meal_data in response.get("dietPlan", {}).items()
    } if response else {}


def fetch_deliveries_for_date(data: dict, target_date: str) -> list:
    """Fetches deliveries for a specific date."""
    return [d for d in data.get("deliveries", []) if d.get("date") == target_date]


def fetch_viking_meal_details(delivery_id: str) -> dict | None:
    """Fetches detailed meal information from Viking for a specific delivery."""
    return VikingClient.get(APIConfig.VIKING_DATE_DETAILS_URL.format(id=delivery_id))


def create_or_find_product(menu_meal_name: str, nutrition: dict, weight: str, target_date: str) -> str | None:
    """Finds an existing product or creates a new product in Fitatu."""
    # Store nutrition values exactly as Viking provides them (for the full portion)
    calories = nutrition.get("calories", "N/A")
    protein = nutrition.get("protein", "N/A")
    carbs = nutrition.get("carbohydrate", "N/A")
    sugar = nutrition.get("sugar", "N/A")
    fat = nutrition.get("fat", "N/A")
    sat_fat = nutrition.get("saturatedFattyAcids", "N/A")
    fiber = nutrition.get("dietaryFiber", "N/A")
    salt = nutrition.get("salt", "N/A")
    
    # Helper function to check if values match (with tiny tolerance for floating point)
    def values_match(existing_val, new_val):
        # If new value is N/A, we can't compare
        if new_val == "N/A":
            return True  # Skip comparison
        # If existing is None but we have a new value, they don't match
        if existing_val is None:
            return True  # Skip comparison if existing data is missing
        try:
            existing = float(existing_val)
            new = float(new_val)
            # Allow 0.1% tolerance only for floating point precision
            return abs(existing - new) <= 0.001 * max(abs(existing), abs(new))
        except (ValueError, TypeError):
            return True  # Skip comparison if conversion fails
    
    # Search for all products with this name
    existing_products = search_all_products(menu_meal_name, target_date)
    
    # Debug: show all found products
    if existing_products:
        logging.info(f"Found {len(existing_products)} products with name '{menu_meal_name}':")
        for p in existing_products:
            logging.info(f"  ID {p.get('foodId')}: {p.get('energy')} kcal, {p.get('protein')}g protein")
    
    # Try to find a product that matches the current nutrition values
    # Match primarily on calories since that's the most reliable value
    matched_product = None
    for product in existing_products:
        # Check if calories match (main criteria)
        calories_match = values_match(product.get("energy"), calories)
        
        if calories_match:
            # Found a product with matching calories - use it
            matched_product = product
            logging.info(f"✓ Matched product ID {product.get('foodId')} with {product.get('energy')} kcal (matches {calories} kcal)")
            break
    
    if matched_product:
        # Delete ALL other products with the same name (keep only the matched one)
        matched_id = matched_product.get("foodId")
        
        duplicates_deleted = 0
        for product in existing_products:
            product_id = product.get("foodId")
            if product_id != matched_id:
                if delete_product(product_id):
                    logging.info(f"  🗑️  Deleted duplicate product ID {product_id} ({product.get('energy')} kcal)")
                    duplicates_deleted += 1
                else:
                    logging.warning(f"  ⚠️ Failed to delete duplicate product ID {product_id}")
        
        if duplicates_deleted > 0:
            logging.info(f"  Cleaned up {duplicates_deleted} duplicate(s) for '{menu_meal_name}'")
        
        return matched_id
    
    # If we found products but none match, log the mismatch
    if existing_products:
        # Show the first product's values as the old values
        first_product = existing_products[0]
        product_id = first_product.get("foodId")
        
        differences = []
        if not values_match(first_product.get("energy"), calories):
            differences.append(f"Calories: {first_product.get('energy')} -> {calories}")
        if not values_match(first_product.get("protein"), protein):
            differences.append(f"Protein: {first_product.get('protein')}g -> {protein}g")
        if not values_match(first_product.get("carbohydrate"), carbs):
            differences.append(f"Carbs: {first_product.get('carbohydrate')}g -> {carbs}g")
        if not values_match(first_product.get("fat"), fat):
            differences.append(f"Fat: {first_product.get('fat')}g -> {fat}g")
        
        if differences:
            logging.warning(f"⚠️ Mismatch found for product ID {product_id}: '{menu_meal_name}' - {', '.join(differences)}")
    
    # Create new product if not found or no matching nutrition
    product_data = {
        "name": menu_meal_name,
        "brand": BRAND,
        "energy": calories,
        "carbohydrate": carbs,
        "sugars": sugar,
        "fat": fat,
        "protein": protein,
        "saturatedFat": sat_fat,
        "fiber": fiber,
        "measures": [{"measureKey": "PACKAGE", "measureUnit": "g", "weight": str(weight)}],
        "salt": salt
    }
    product_id = create_product(product_data)
    if product_id:
        logging.info(f"  Created new product ID: {product_id}")
    return product_id


def process_meal(delivery: dict, target_date: str) -> tuple[str, str]:
    """Processes a single meal and returns its product ID and weight."""
    delivery_id = delivery["deliveryId"]
    viking_date_data = fetch_viking_meal_details(delivery_id)
    if not viking_date_data:
        logging.error(f"Failed to retrieve delivery details for {delivery_id}")
        return None, None

    meal_ids, meal_weights = {}, {}
    for meal in viking_date_data.get("deliveryMenuMeal", []):
        if meal.get("deliveryMealId") is None:
            logging.info(f"Skipping '{meal.get("mealName", "")}' - there is no develivery")
            continue

        menu_meal_name = meal.get("menuMealName")
        if (menu_meal_name):
            meal_name = meal.get("mealName", "")
            nutrition = meal.get("nutrition", {})
            weight = nutrition.get("weight", "N/A")

            product_id = create_or_find_product(menu_meal_name, nutrition, weight, target_date)
            if product_id:
                meal_ids[meal_name] = product_id
                meal_weights[meal_name] = weight
    return meal_ids, meal_weights


def process_date(target_date: str, data: dict) -> dict:
    """Refactored process_date function that processes all deliveries for a given date."""
    deliveries_on_date = fetch_deliveries_for_date(data, target_date)

    if not deliveries_on_date:
        logging.info(f"No meals found for {target_date}")
        return {"meal_ids": {}, "meal_weights": {}}

    all_meal_ids, all_meal_weights = {}, {}
    for delivery in deliveries_on_date:
        meal_ids, meal_weights = process_meal(delivery, target_date)
        if meal_ids:
            all_meal_ids.update(meal_ids)
            all_meal_weights.update(meal_weights)

    return {"meal_ids": all_meal_ids, "meal_weights": all_meal_weights}


def add_meal_to_diet_plan(diet_plan: dict, meal_name: str, meal_id: str, meal_weight: int, existing_plan: dict):
    """Adds a meal to the diet plan while avoiding duplicates."""
    mapped_key = MEAL_MAPPING.get(meal_name)
    if not mapped_key:
        logging.info(f"Skipping '{meal_name}' - not supported meal by mapping configuration")
        return

    # Check if this exact product ID already exists
    if meal_id and mapped_key in existing_plan and any(item.get("productId") == meal_id for item in existing_plan[mapped_key]):
        logging.info(f"Skipping '{meal_name}' - already exists in diet plan with same product")
        return

    diet_plan.setdefault(mapped_key, {"items": []})["items"].append({
        "planDayDietItemId": str(uuid.uuid1()),
        "foodType": "PRODUCT",
        "measureId": 1,
        "measureQuantity": int(meal_weight),
        "productId": meal_id,
        "source": "API",
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    logging.info(f"Added '{meal_name}' to diet plan ({meal_weight}g, product ID: {meal_id})")


def publish_diet_plan(date: str, meal_ids: dict, meal_weights: dict):
    """Publishes the diet plan to Fitatu."""
    existing_plan = get_existing_diet_plan(date)
    diet_plan = {date: {"dietPlan": {}}}

    # Mark meals with outdated product IDs for deletion (only if new product ID differs)
    for meal_key, items in existing_plan.items():
        items_to_keep = []
        for item in items:
            # Only mark for deletion if this product is from Viking brand but not in current meal IDs
            if item["productId"] not in meal_ids.values():
                item["deletedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            items_to_keep.append(item)
        
        # Keep all items (both marked for deletion and existing ones)
        if items_to_keep:
            diet_plan[date]["dietPlan"][meal_key] = {"items": items_to_keep}  

    # Add new meals (will skip if same product ID already exists)
    for meal_name, meal_id in meal_ids.items():
        add_meal_to_diet_plan(diet_plan[date]["dietPlan"], meal_name, meal_id, meal_weights.get(meal_name, 100), existing_plan)

    if FitatuClient.post(APIConfig.FITATU_DIET_PLAN_URL, diet_plan):
        logging.info(f"Fitatu Diet Plan updated for {date}")
    else:
        logging.error(f"Failed to update diet plan for {date}")


def main():
    """Main execution flow."""
    order_data = VikingClient.get(APIConfig.VIKING_ORDER_URL.format(id=VIKING_ORDER_ID))
    if not order_data:
        logging.error("Failed to retrieve orders")
        return

    for target_date in select_dates():
        logging.info(f"Processing {target_date}")
        result = process_date(target_date, order_data)

        publish_diet_plan(target_date, result["meal_ids"], result["meal_weights"])


if __name__ == "__main__":
    main()
