let currentUser = null;
let fetchPromise = null;

export async function getCurrentUser() {
    if (currentUser) {
        return currentUser;
    }

    // Return in-progress fetch to prevent duplicate API calls
    if (fetchPromise) {
        return fetchPromise;
    }

    const token = localStorage.getItem("access_token");
    if (!token) {
        return null;
    }

    fetchPromise = (async () => {
        try {
            const response = await fetch("/api/users/me", {
                headers: {
                    Authorization: `Bearer ${token}`,
                },
            });

            if (response.ok) {
                currentUser = await response.json();
                return currentUser;
            }

            localStorage.removeItem("access_token");
            localStorage.removeItem("refresh_token");
            return null;
        } catch (error) {
            console.error("Error fetching current user:", error);
            return null;
        } finally {
            fetchPromise = null;
        }
    })();

    return fetchPromise;
}

export async function logout() {
    const refreshToken = localStorage.getItem("refresh_token");
    if (refreshToken) {
        try {
            await fetch("/api/users/logout", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ refresh_token: refreshToken }),
            });
        } catch (error) {
            console.error("Error revoking refresh token:", error);
        }
    }

    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    currentUser = null;
    window.location.href = "/";
}

export function getToken() {
    return localStorage.getItem("access_token");
}

export function setToken(token) {
    localStorage.setItem("access_token", token);
}

export function clearUserCache() {
    currentUser = null;
}
