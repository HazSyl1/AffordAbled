from httpx import AsyncClient

from tests.helpers import DEFAULT_CATEGORIES, auth_headers, register_and_get_token


async def test_categories_router_smoke(client: AsyncClient) -> None:
    token = await register_and_get_token(client, 'categories-smoke@example.com')

    create_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Weekend Dining', 'type': 'expense', 'icon': 'utensils', 'color': '#22c55e'},
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201
    category_id = create_response.json()['id']

    list_response = await client.get('/api/v1/categories', headers=auth_headers(token))
    assert list_response.status_code == 200
    assert len(list_response.json()) == len(DEFAULT_CATEGORIES) + 1

    patch_response = await client.patch(
        f'/api/v1/categories/{category_id}',
        json={'name': 'Food and Dining', 'icon': 'restaurant', 'color': '#16a34a'},
        headers=auth_headers(token),
    )
    assert patch_response.status_code == 200
    assert patch_response.json()['name'] == 'Food and Dining'

    delete_response = await client.delete(f'/api/v1/categories/{category_id}', headers=auth_headers(token))
    assert delete_response.status_code == 204

    final_list_response = await client.get('/api/v1/categories', headers=auth_headers(token))
    assert final_list_response.status_code == 200
    assert {(item['name'], item['type']) for item in final_list_response.json()} == DEFAULT_CATEGORIES


async def test_user_cannot_modify_another_users_category(client: AsyncClient) -> None:
    owner_token = await register_and_get_token(client, 'owner-category@example.com')
    other_token = await register_and_get_token(client, 'other-category@example.com')

    create_response = await client.post(
        '/api/v1/categories',
        json={'name': 'Private Transport', 'type': 'expense'},
        headers=auth_headers(owner_token),
    )
    assert create_response.status_code == 201
    category_id = create_response.json()['id']

    patch_response = await client.patch(
        f'/api/v1/categories/{category_id}',
        json={'name': 'Hacked Name'},
        headers=auth_headers(other_token),
    )
    assert patch_response.status_code == 404

    delete_response = await client.delete(f'/api/v1/categories/{category_id}', headers=auth_headers(other_token))
    assert delete_response.status_code == 404


async def test_new_users_receive_private_default_categories(client: AsyncClient) -> None:
    first_token = await register_and_get_token(client, 'defaults-first@example.com')
    second_token = await register_and_get_token(client, 'defaults-second@example.com')

    first_categories = await client.get('/api/v1/categories', headers=auth_headers(first_token))
    second_categories = await client.get('/api/v1/categories', headers=auth_headers(second_token))

    first_items = first_categories.json()
    second_items = second_categories.json()
    assert {(item['name'], item['type']) for item in first_items} == DEFAULT_CATEGORIES
    assert {(item['name'], item['type']) for item in second_items} == DEFAULT_CATEGORIES
    assert {item['id'] for item in first_items}.isdisjoint({item['id'] for item in second_items})
