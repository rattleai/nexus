# Quick Testing Guide - Error Fixes

## Run the App

```bash
cd frontend
npm run dev
```

The app will start on `http://localhost:5173`

## Test Case 1: Normal Flow (Should Work)

1. Navigate to login page
2. Enter valid credentials
3. Click login
4. **Expected**:
   - ✅ Dashboard loads
   - ✅ NotificationBell appears in header with count
   - ✅ No console errors
   - ✅ Clicking notifications works

## Test Case 2: Auth Token Expiration (Most Important Fix)

**Simulate expired refresh token:**

1. Open browser DevTools (F12)
2. Go to Application → Cookies
3. Find `refresh_token` or similar auth cookie
4. Delete it
5. Refresh the page

**Expected Behavior AFTER FIX**:
- ✅ Page loads normally
- ✅ Shows login screen (not blank/error)
- ✅ NotificationBell still renders (not crashed)
- ✅ Console shows: `"Session restoration failed - user not authenticated"`
- ❌ **NO ERROR**: "Cannot read properties of null (reading 'plan')"
- ❌ **NO ERROR**: Unhandled promise rejection about 401/403

**Before the fix**, the page would:
- ❌ Crash or show blank screen
- ❌ Show "Cannot read properties of null" error
- ❌ NotificationBell broken

## Test Case 3: Network Error During Load

**Simulate slow/failing network:**

1. Open DevTools → Network tab
2. Set throttling to "Slow 3G" or "Offline"
3. Refresh page

**Expected**:
- ✅ App shows loading state
- ✅ Will retry queries automatically (1 retry with 1000ms delay)
- ✅ After enabling network again, queries complete
- ✅ No "Cannot read" errors

## Test Case 4: Check Console Logs

Open DevTools → Console tab and look for these (good signs):

```
✅ Good signs:
- "Session restoration failed - user not authenticated" (when no token)
- "Failed to fetch notifications: [error]" (when API down, but graceful)
- "Token refresh failed" (when refresh endpoint unreachable)

❌ Bad signs (should NOT see):
- "Cannot read properties of null"
- "Cannot read property 'plan' of undefined"
- Unhandled promise rejections
- Stack traces from NotificationBell component
```

## Test Case 5: Billing Page (Tests use-billing & use-usage fixes)

1. Login successfully
2. Navigate to Billing page (in sidebar)

**Expected**:
- ✅ Current Plan shows with name (not null/undefined)
- ✅ Usage bars show with numbers
- ✅ Plans list loads
- ✅ No "Cannot read 'plan'" errors

**To test error case**:
1. Go to Billing page
2. Throttle network to offline
3. Try to load a plan
4. **Expected**: Error message appears, can retry (not crash)

## Code Changes You Can Review

### 1. auth-context.tsx (Session Management)
Look for these lines (around line 66-72):
```typescript
catch (err) {
  // No valid refresh token — user is not authenticated
  if (!cancelled) {
    syncToken(null, _setAccessToken)    // ← Clears token
    setUser(null)                        // ← Clears user
    console.debug("Session restoration failed...")
  }
}
```

### 2. api-client.ts (Request Interceptors)
Look for (around line 89-95):
```typescript
if (response.status === 401 && _accessToken) {
  const refreshed = await attemptTokenRefresh()
  if (refreshed && _accessToken) {
    // Retry with new token
    request.headers.set("Authorization", `Bearer ${_accessToken}`)
    return ky(request, options)
  }
  // If refresh failed, allow the 401 to propagate
}
```

### 3. use-notifications.ts (Error Handling)
Look for (around line 9-11):
```typescript
catch (error) {
  console.warn("Failed to fetch notifications:", error)
  return []    // ← Returns empty array instead of throwing
}
```

### 4. use-usage.ts (Null Safety)
Look for (around line 25-33):
```typescript
if (subscriptionResult.status === "fulfilled" && subscriptionResult.value) {
  try {
    limits = subscriptionResult.value.plan?.limits ?? {}
  } catch (err) {
    console.warn("Failed to extract subscription limits:", err)
  }
}
```

## Debugging Tips

If you encounter issues:

### Check 1: Are tokens being set?
```javascript
// In browser console:
import { getAccessToken } from '@/lib/api-client'
console.log(getAccessToken())  // Should show token if logged in
```

### Check 2: Is auth-context working?
```javascript
// If you have React DevTools, find <AuthProvider>
// Check its state:
// - user: should be object or null
// - accessToken: should be string or null
// - isLoading: should be false when done
```

### Check 3: Are queries retrying?
```javascript
// In console, look for these messages:
"Failed to fetch notifications: Error..."
"Retrying query..."  // (React Query adds this automatically)
```

### Check 4: Check Network Requests
1. DevTools → Network tab
2. Filter to "fetch/XHR"
3. Look for:
   - `POST /auth/refresh` - Should see this on page load
   - `GET /notifications` - Should retry if fails with 401
   - Response status codes (should see 401 → retry pattern)

## Common Issues & Solutions

### Issue: "Cannot read properties of null (reading 'plan')"
**Status**: FIXED ✅
**Location**: Was in use-usage.ts line 27
**Solution**: Added null checks before accessing `.plan`

### Issue: Blank page after login (no error message)
**Status**: FIXED ✅
**Location**: Was in auth-context.tsx line 65
**Solution**: Now clears token and shows login instead

### Issue: NotificationBell shows but always empty
**Expected Behavior** (After fix) ✅
**Not a bug** - Happens when:
- User just logged in (notifications may take time to load)
- No notifications exist
- If API is down, shows empty instead of error

### Issue: 403 errors on refresh endpoint
**Status**: Gracefully handled ✅
**Location**: auth-context.tsx and api-client.ts
**Solution**: Treats as session expiration, logs debug message

## Summary of What's Fixed

| Error | Status | Test Case |
|-------|--------|-----------|
| "Cannot read properties of null" | ✅ FIXED | Case 4 (Billing page) |
| 403 Forbidden on refresh | ✅ FIXED | Case 2 (Delete token) |
| 401 Unauthorized on notifications | ✅ FIXED | Case 2 (Shows empty safely) |
| Unread count errors | ✅ FIXED | Case 2 (Returns 0 safely) |

## Report Issues

If you find any remaining issues:

1. Reproduce the problem with exact steps
2. Open DevTools Console and note any errors
3. Check the Network tab for failing requests
4. Note the API response status code

Then either:
- Check if it's in the "Known Issues" section below
- Or provide the steps + console output for investigation

## Known Issues

**None** - All major error cases have been addressed.

If the app crashes with any of these errors, something is wrong:
- "Cannot read properties of null"
- "Cannot read property 'X' of undefined"
- Unhandled promise rejection in NotificationBell or billing page

These should now all be handled gracefully.
