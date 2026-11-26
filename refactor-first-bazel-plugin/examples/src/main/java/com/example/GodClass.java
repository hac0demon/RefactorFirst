package com.example;

/**
 * A sample class that mimics a "God Class" to demonstrate how RefactorFirst
 * identifies and ranks class disharmonies.
 */
public class GodClass {

    private String name;
    private int age;
    private double salary;
    private String address;
    private String email;
    private String phoneNumber;
    private String department;
    private boolean active;

    public void processUser() {
        if (name != null) {
            System.out.println("Processing user: " + name);
        }
        if (age > 18) {
            System.out.println("User is an adult");
        }
        updateDatabase();
        sendEmailNotification();
        generateReport();
    }

    public void updateDatabase() {
        System.out.println("Updating database entry for " + name);
        // DB code logic here...
    }

    public void sendEmailNotification() {
        System.out.println("Sending email to " + email);
        // Mail code logic here...
    }

    public void generateReport() {
        System.out.println("Generating report for " + department);
        // Reporting code logic here...
    }

    public void manageInventory() {
        System.out.println("Managing inventory items...");
    }

    public void calculateTaxes() {
        salary = salary * 0.8;
    }

    // Boilerplate getters and setters
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public int getAge() { return age; }
    public void setAge(int age) { this.age = age; }
    public double getSalary() { return salary; }
    public void setSalary(double salary) { this.salary = salary; }
    public String getAddress() { return address; }
    public void setAddress(String address) { this.address = address; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getPhoneNumber() { return phoneNumber; }
    public void setPhoneNumber(String phoneNumber) { this.phoneNumber = phoneNumber; }
    public String getDepartment() { return department; }
    public void setDepartment(String department) { this.department = department; }
    public boolean isActive() { return active; }
    public void setActive(boolean active) { this.active = active; }
}
