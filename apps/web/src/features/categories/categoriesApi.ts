import { apiClient } from '../../lib/apiClient';

export type CategoryType = 'expense' | 'income';

export interface Category {
  id: string;
  name: string;
  type: CategoryType;
  icon: string | null;
  color: string | null;
  created_at: string;
}

export interface CreateCategoryRequest {
  name: string;
  type: CategoryType;
  icon?: string;
  color?: string;
}

const categoriesApi = apiClient.injectEndpoints({
  endpoints: (builder) => ({
    listCategories: builder.query<Category[], void>({
      query: () => '/categories',
      providesTags: ['Category'],
    }),
    createCategory: builder.mutation<Category, CreateCategoryRequest>({
      query: (body) => ({ url: '/categories', method: 'POST', body }),
      invalidatesTags: ['Category'],
    }),
  }),
});

export const { useListCategoriesQuery, useCreateCategoryMutation } = categoriesApi;
