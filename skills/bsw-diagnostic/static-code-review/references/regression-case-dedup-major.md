# Regression Case: Deduplicate To One Major

Use this case to verify that the standalone workflow removes duplicates and keeps one specific behavior-impacting defect.

## Scenario

Input type:

1. Focused code snippet.
2. Optional supporting finding list or exported report.

Code under review:

```c
uint8 APLCUST_GetActualYear_UB(Date_ST *pDate)
{
    uint8 l_actualYear_u8;
    sint16 l_OrdinalDay_s16;
    uint16 l_DaysPerYear_u16;

    l_OrdinalDay_s16 = (sint16)(((pDate->CalendarWeek_u8 * 7U) + pDate->DayOfWeek_u8) - (APLCUST_Get4thJanDay_UB(pDate->Year_u8) + 3U));

    if( 0U >= l_OrdinalDay_s16 )
    {
        l_actualYear_u8 = pDate->Year_u8 - 1U;
    }
    else
    {
        l_DaysPerYear_u16 = APLCUST_GetDaysPerYear_UW(pDate->Year_u8);

        if( (uint16)l_OrdinalDay_s16 > l_DaysPerYear_u16 )
        {
            l_actualYear_u8 = pDate->Year_u8 + 1U;
        }
        else
        {
            l_actualYear_u8 = pDate->Year_u8;
        }
    }

    return l_actualYear_u8;
}
```

Candidate findings:

1. Signed/unsigned comparison on `0U >= l_OrdinalDay_s16` changes behavior for negative values.
2. Pointer `pDate` is dereferenced without a null check.
3. Pointer `pDate` is dereferenced without a null check under a generic runtime-error rule.
4. Explicit cast lacks a reason comment.
5. File is missing a copyright notice.

## Expected Review Outcome

Confirmed Findings:

1. Keep exactly one `major` finding for the signed/unsigned comparison defect.

Open Questions:

1. Keep the `pDate` contract question here if nullability is not proven.
2. Keep year-range boundary questions here if the domain is not documented.

Suspected But Unconfirmed Issues:

1. None required.

Removed Or Downgraded Items:

1. Remove the generic null-pointer duplicate because it adds no new action beyond the more specific null-pointer concern.
2. Do not keep the null-pointer concern as a confirmed defect when the caller contract is unavailable.
3. Remove the explicit-cast-comment item from confirmed findings because it is a documentation or reviewability issue, not the proven behavior defect.
4. Remove the copyright item from confirmed findings because it is non-functional.

## Why This Case Matters

This case verifies that the workflow keeps a direct code review result focused, deduplicated, and defensible. The expected result is a smaller but stronger final finding set.